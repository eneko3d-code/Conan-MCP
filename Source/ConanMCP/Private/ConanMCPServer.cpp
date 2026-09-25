#include "ConanMCPServer.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPSettings.h"
#include "ConanMCPModule.h"
#include "Async/Async.h"
#include "Serialization/JsonReader.h"
#include "Serialization/JsonSerializer.h"
#include "Common/TcpListener.h"

FConanMCPServer& FConanMCPServer::Get()
{
	static FConanMCPServer Instance;
	return Instance;
}

FConanMCPServer::FConanMCPServer()
{
}

FConanMCPServer::~FConanMCPServer()
{
	StopServer();
}

bool FConanMCPServer::StartServer(const FString& InBindAddress, int32 InPort)
{
	FScopeLock Lock(&ServerLock);

	if (bIsRunning)
	{
		StopServer();
	}

	BindAddress = InBindAddress.IsEmpty() ? TEXT("127.0.0.1") : InBindAddress;
	Port = InPort > 0 ? InPort : 8123;

	FIPv4Address LocalAddr;
	if (!FIPv4Address::Parse(BindAddress, LocalAddr))
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Failed to parse Bind Address '%s'"), *BindAddress);
		return false;
	}

	FIPv4Endpoint Endpoint(LocalAddr, Port);
	ISocketSubsystem* SocketSubsystem = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM);
	if (!SocketSubsystem)
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: SocketSubsystem not available"));
		return false;
	}

	ListenerSocket = SocketSubsystem->CreateSocket(NAME_Stream, TEXT("ConanMCPServerListener"), false);
	if (!ListenerSocket)
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Failed to create listener socket"));
		return false;
	}

	ListenerSocket->SetReuseAddr(true);
	ListenerSocket->SetNonBlocking(true);

	TSharedRef<FInternetAddr> InternetAddr = SocketSubsystem->CreateInternetAddr();
	InternetAddr->SetIp(LocalAddr.Value);
	InternetAddr->SetPort(Port);

	if (!ListenerSocket->Bind(*InternetAddr))
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Failed to bind to %s:%d (Port may be in use)"), *BindAddress, Port);
		SocketSubsystem->DestroySocket(ListenerSocket);
		ListenerSocket = nullptr;
		return false;
	}

	if (!ListenerSocket->Listen(8))
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Failed to listen on socket %s:%d"), *BindAddress, Port);
		SocketSubsystem->DestroySocket(ListenerSocket);
		ListenerSocket = nullptr;
		return false;
	}

	bStopping = false;
	bIsRunning = true;

	Thread = FRunnableThread::Create(this, TEXT("ConanMCPServerWorker"), 128 * 1024, TPri_Normal);
	if (!Thread)
	{
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Failed to create server worker thread"));
		bIsRunning = false;
		SocketSubsystem->DestroySocket(ListenerSocket);
		ListenerSocket = nullptr;
		return false;
	}

	UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: MCP server started on %s:%d (Endpoint: /mcp)"), *BindAddress, Port);
	return true;
}

void FConanMCPServer::StopServer()
{
	FScopeLock Lock(&ServerLock);

	if (!bIsRunning && !Thread)
	{
		return;
	}

	bStopping = true;
	bIsRunning = false;

	if (ListenerSocket)
	{
		ListenerSocket->Close();
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ListenerSocket);
		ListenerSocket = nullptr;
	}

	if (Thread)
	{
		Thread->WaitForCompletion();
		delete Thread;
		Thread = nullptr;
	}

	UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: MCP server stopped"));
}

bool FConanMCPServer::RestartServer()
{
	FString CurrentAddress = BindAddress;
	int32 CurrentPort = Port;
	StopServer();
	return StartServer(CurrentAddress, CurrentPort);
}

bool FConanMCPServer::Init()
{
	return true;
}

uint32 FConanMCPServer::Run()
{
	while (!bStopping && ListenerSocket)
	{
		bool bHasPendingConnection = false;
		if (ListenerSocket->HasPendingConnection(bHasPendingConnection) && bHasPendingConnection)
		{
			TSharedRef<FInternetAddr> ClientAddr = ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->CreateInternetAddr();
			FSocket* ClientSocket = ListenerSocket->Accept(*ClientAddr, TEXT("ConanMCPClientConnection"));

			if (ClientSocket)
			{
				ConnectedClients.Increment();
				HandleClient(ClientSocket);
				ConnectedClients.Decrement();
			}
		}

		FPlatformProcess::Sleep(0.01f); // 10ms poll
	}

	return 0;
}

void FConanMCPServer::Stop()
{
	bStopping = true;
}

void FConanMCPServer::Exit()
{
}

void FConanMCPServer::HandleClient(FSocket* ClientSocket)
{
	if (!ClientSocket) return;

	// Read HTTP request headers and body
	TArray<uint8> ReceivedData;
	uint8 Buffer[4096];
	int32 BytesRead = 0;

	// Non-blocking loop to read with timeout
	double StartTime = FPlatformTime::Seconds();
	bool bHeadersComplete = false;
	int32 ExpectedContentLength = -1;
	int32 HeaderEndIndex = -1;

	while (!bStopping && (FPlatformTime::Seconds() - StartTime) < 5.0)
	{
		uint32 PendingDataSize = 0;
		if (ClientSocket->HasPendingData(PendingDataSize) && PendingDataSize > 0)
		{
			if (ClientSocket->Recv(Buffer, sizeof(Buffer), BytesRead, ESocketReceiveFlags::None) && BytesRead > 0)
			{
				ReceivedData.Append(Buffer, BytesRead);

				// Look for \r\n\r\n
				if (!bHeadersComplete)
				{
					for (int32 i = 3; i < ReceivedData.Num(); i++)
					{
						if (ReceivedData[i - 3] == '\r' && ReceivedData[i - 2] == '\n' &&
							ReceivedData[i - 1] == '\r' && ReceivedData[i] == '\n')
						{
							bHeadersComplete = true;
							HeaderEndIndex = i + 1;
							break;
						}
					}

					if (bHeadersComplete)
					{
						// Parse Content-Length
						FString HeaderStr;
						FFileHelper::BufferToString(HeaderStr, ReceivedData.GetData(), HeaderEndIndex);

						TArray<FString> HeaderLines;
						HeaderStr.ParseIntoStringLines(HeaderLines);
						for (const FString& Line : HeaderLines)
						{
							if (Line.StartsWith(TEXT("Content-Length:"), ESearchCase::IgnoreCase))
							{
								FString LenStr = Line.RightChop(15).TrimStartAndEnd();
								ExpectedContentLength = FCString::Atoi(*LenStr);
								break;
							}
						}
					}
				}

				if (bHeadersComplete)
				{
					int32 CurrentBodyBytes = ReceivedData.Num() - HeaderEndIndex;
					if (ExpectedContentLength <= 0 || CurrentBodyBytes >= ExpectedContentLength)
					{
						break;
					}
				}
			}
		}
		else
		{
			FPlatformProcess::Sleep(0.005f);
		}
	}

	if (ReceivedData.Num() == 0 || !bHeadersComplete)
	{
		ClientSocket->Close();
		ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
		return;
	}

	TotalRequests.Increment();

	FString RequestHeaders;
	FFileHelper::BufferToString(RequestHeaders, ReceivedData.GetData(), HeaderEndIndex);

	FString Method = TEXT("GET");
	if (RequestHeaders.StartsWith(TEXT("POST"))) Method = TEXT("POST");
	else if (RequestHeaders.StartsWith(TEXT("OPTIONS"))) Method = TEXT("OPTIONS");

	FString ResponseBody;
	FString ResponseStatus = TEXT("200 OK");

	if (Method == TEXT("OPTIONS"))
	{
		// CORS Preflight
		ResponseBody = TEXT("");
	}
	else if (Method == TEXT("GET"))
	{
		// Provide basic health info on GET
		TSharedPtr<FJsonObject> StatusObj = MakeShared<FJsonObject>();
		StatusObj->SetStringField(TEXT("service"), TEXT("ConanMCP"));
		StatusObj->SetStringField(TEXT("version"), TEXT("1.0.0"));
		StatusObj->SetStringField(TEXT("protocol"), TEXT("MCP / JSON-RPC 2.0"));
		StatusObj->SetStringField(TEXT("status"), TEXT("running"));
		StatusObj->SetNumberField(TEXT("registered_tools"), FConanMCPToolRegistry::Get().GetToolCount());

		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ResponseBody);
		FJsonSerializer::Serialize(StatusObj.ToSharedRef(), Writer);
	}
	else if (Method == TEXT("POST"))
	{
		FString RequestBody;
		if (HeaderEndIndex < ReceivedData.Num())
		{
			FFileHelper::BufferToString(RequestBody, ReceivedData.GetData() + HeaderEndIndex, ReceivedData.Num() - HeaderEndIndex);
		}

		ResponseBody = ProcessJsonRpc(RequestBody);
	}

	// Send HTTP response
	FTCHARToUTF8 Utf8Body(*ResponseBody);
	FString HttpResponse = FString::Printf(
		TEXT("HTTP/1.1 %s\r\n")
		TEXT("Content-Type: application/json; charset=utf-8\r\n")
		TEXT("Content-Length: %d\r\n")
		TEXT("Access-Control-Allow-Origin: *\r\n")
		TEXT("Access-Control-Allow-Methods: POST, GET, OPTIONS\r\n")
		TEXT("Access-Control-Allow-Headers: Content-Type, Authorization\r\n")
		TEXT("Connection: close\r\n\r\n"),
		*ResponseStatus,
		Utf8Body.Length()
	);

	FTCHARToUTF8 Utf8Headers(*HttpResponse);
	int32 Sent = 0;
	ClientSocket->Send((const uint8*)Utf8Headers.Get(), Utf8Headers.Length(), Sent);
	if (Utf8Body.Length() > 0)
	{
		ClientSocket->Send((const uint8*)Utf8Body.Get(), Utf8Body.Length(), Sent);
	}

	ClientSocket->Close();
	ISocketSubsystem::Get(PLATFORM_SOCKETSUBSYSTEM)->DestroySocket(ClientSocket);
}

FString FConanMCPServer::ProcessJsonRpc(const FString& RequestJsonStr)
{
	TSharedPtr<FJsonObject> RequestObj;
	TSharedRef<TJsonReader<>> Reader = TJsonReaderFactory<>::Create(RequestJsonStr);

	if (!FJsonSerializer::Deserialize(Reader, RequestObj) || !RequestObj.IsValid())
	{
		TotalErrors.Increment();
		TSharedPtr<FJsonObject> Err = MakeErrorResponse(nullptr, -32700, TEXT("Parse error: Invalid JSON"));
		FString Output;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Output);
		FJsonSerializer::Serialize(Err.ToSharedRef(), Writer);
		return Output;
	}

	// Check jsonrpc version
	FString Version = RequestObj->GetStringField(TEXT("jsonrpc"));
	TSharedPtr<FJsonValue> IdVal = RequestObj->TryGetField(TEXT("id"));
	FString Method = RequestObj->GetStringField(TEXT("method"));

	TSharedPtr<FJsonObject> ResponseObj;

	if (Method == TEXT("initialize"))
	{
		ResponseObj = HandleInitialize(RequestObj, IdVal);
	}
	else if (Method == TEXT("notifications/initialized"))
	{
		// MCP client notification acknowledgment
		UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: Client initialized"));
		ResponseObj = MakeSuccessResponse(IdVal, MakeShared<FJsonObject>());
	}
	else if (Method == TEXT("ping"))
	{
		ResponseObj = HandlePing(RequestObj, IdVal);
	}
	else if (Method == TEXT("tools/list"))
	{
		ResponseObj = HandleToolsList(RequestObj, IdVal);
	}
	else if (Method == TEXT("tools/call"))
	{
		ResponseObj = HandleToolsCall(RequestObj, IdVal);
	}
	else
	{
		TotalErrors.Increment();
		ResponseObj = MakeErrorResponse(IdVal, -32601, FString::Printf(TEXT("Method not found: '%s'"), *Method));
	}

	FString ResultStr;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ResultStr);
	FJsonSerializer::Serialize(ResponseObj.ToSharedRef(), Writer);
	return ResultStr;
}

TSharedPtr<FJsonObject> FConanMCPServer::HandleInitialize(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetStringField(TEXT("protocolVersion"), TEXT("2024-11-05"));

	TSharedPtr<FJsonObject> ServerInfo = MakeShared<FJsonObject>();
	ServerInfo->SetStringField(TEXT("name"), TEXT("conan-devkit-mcp"));
	ServerInfo->SetStringField(TEXT("version"), TEXT("1.0.0"));
	Result->SetObjectField(TEXT("serverInfo"), ServerInfo);

	TSharedPtr<FJsonObject> Capabilities = MakeShared<FJsonObject>();
	TSharedPtr<FJsonObject> ToolsCap = MakeShared<FJsonObject>();
	ToolsCap->SetBoolField(TEXT("listChanged"), false);
	Capabilities->SetObjectField(TEXT("tools"), ToolsCap);
	Result->SetObjectField(TEXT("capabilities"), Capabilities);

	UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: MCP client connected and initializing"));
	return MakeSuccessResponse(IdVal, Result);
}

TSharedPtr<FJsonObject> FConanMCPServer::HandlePing(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal)
{
	return MakeSuccessResponse(IdVal, MakeShared<FJsonObject>());
}

TSharedPtr<FJsonObject> FConanMCPServer::HandleToolsList(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal)
{
	TSharedPtr<FJsonObject> Result = MakeShared<FJsonObject>();
	Result->SetArrayField(TEXT("tools"), FConanMCPToolRegistry::Get().GetToolsJsonList());
	return MakeSuccessResponse(IdVal, Result);
}

TSharedPtr<FJsonObject> FConanMCPServer::HandleToolsCall(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal)
{
	const TSharedPtr<FJsonObject>* ParamsObj = nullptr;
	if (!RequestObj->TryGetObjectField(TEXT("params"), ParamsObj) || !ParamsObj || !ParamsObj->IsValid())
	{
		TotalErrors.Increment();
		return MakeErrorResponse(IdVal, -32602, TEXT("Invalid params: 'params' object required"));
	}

	FString ToolName;
	if (!(*ParamsObj)->TryGetStringField(TEXT("name"), ToolName) || ToolName.IsEmpty())
	{
		TotalErrors.Increment();
		return MakeErrorResponse(IdVal, -32602, TEXT("Invalid params: 'name' field required"));
	}

	TSharedPtr<FJsonObject> Arguments = MakeShared<FJsonObject>();
	const TSharedPtr<FJsonObject>* ArgsField = nullptr;
	if ((*ParamsObj)->TryGetObjectField(TEXT("arguments"), ArgsField) && ArgsField && ArgsField->IsValid())
	{
		Arguments = *ArgsField;
	}

	// CRITICAL THREAD SAFETY:
	// Execute on Game Thread via AsyncTask and wait with timeout
	const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();
	float TimeoutSec = Settings ? Settings->CommandTimeoutSeconds : 30.0f;

	TSharedPtr<FConanMCPToolResult> ExecutionResult = MakeShared<FConanMCPToolResult>();
	FEvent* CompletionEvent = FPlatformProcess::GetSynchEventFromPool(false);

	AsyncTask(ENamedThreads::GameThread, [ToolName, Arguments, ExecutionResult, CompletionEvent]()
	{
		*ExecutionResult = FConanMCPToolRegistry::Get().ExecuteTool(ToolName, Arguments);
		CompletionEvent->Trigger();
	});

	bool bCompleted = CompletionEvent->Wait(FTimespan::FromSeconds(TimeoutSec));
	FPlatformProcess::ReturnSynchEventToPool(CompletionEvent);

	if (!bCompleted)
	{
		TotalErrors.Increment();
		UE_LOG(LogConanMCP, Error, TEXT("ConanMCP: Tool execution timed out after %.1f seconds: %s"), TimeoutSec, *ToolName);
		return MakeErrorResponse(IdVal, -32000, FString::Printf(TEXT("Tool execution timed out after %.1f seconds"), TimeoutSec));
	}

	if (!ExecutionResult->bSuccess)
	{
		TotalErrors.Increment();
		return MakeErrorResponse(IdVal, ExecutionResult->ErrorCode != 0 ? ExecutionResult->ErrorCode : -32603, ExecutionResult->ErrorMessage);
	}

	// Standard MCP tool call result schema:
	// result: { content: [ { type: "text", text: "<json string>" } ], isError: false }
	FString ContentStr;
	TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&ContentStr);
	FJsonSerializer::Serialize(ExecutionResult->ResultData.ToSharedRef(), Writer);

	TSharedPtr<FJsonObject> ContentItem = MakeShared<FJsonObject>();
	ContentItem->SetStringField(TEXT("type"), TEXT("text"));
	ContentItem->SetStringField(TEXT("text"), ContentStr);

	TArray<TSharedPtr<FJsonValue>> ContentArray;
	ContentArray.Add(MakeShared<FJsonValueObject>(ContentItem));

	TSharedPtr<FJsonObject> McpResultObj = MakeShared<FJsonObject>();
	McpResultObj->SetArrayField(TEXT("content"), ContentArray);
	McpResultObj->SetBoolField(TEXT("isError"), false);

	return MakeSuccessResponse(IdVal, McpResultObj);
}

TSharedPtr<FJsonObject> FConanMCPServer::MakeErrorResponse(const TSharedPtr<FJsonValue>& IdVal, int32 Code, const FString& Message)
{
	TSharedPtr<FJsonObject> Resp = MakeShared<FJsonObject>();
	Resp->SetStringField(TEXT("jsonrpc"), TEXT("2.0"));
	if (IdVal.IsValid())
	{
		Resp->SetField(TEXT("id"), IdVal);
	}
	else
	{
		Resp->SetField(TEXT("id"), MakeShared<FJsonValueNull>());
	}

	TSharedPtr<FJsonObject> Err = MakeShared<FJsonObject>();
	Err->SetNumberField(TEXT("code"), Code);
	Err->SetStringField(TEXT("message"), Message);
	Resp->SetObjectField(TEXT("error"), Err);

	return Resp;
}

TSharedPtr<FJsonObject> FConanMCPServer::MakeSuccessResponse(const TSharedPtr<FJsonValue>& IdVal, const TSharedPtr<FJsonObject>& ResultData)
{
	TSharedPtr<FJsonObject> Resp = MakeShared<FJsonObject>();
	Resp->SetStringField(TEXT("jsonrpc"), TEXT("2.0"));
	if (IdVal.IsValid())
	{
		Resp->SetField(TEXT("id"), IdVal);
	}
	else
	{
		Resp->SetField(TEXT("id"), MakeShared<FJsonValueNull>());
	}
	Resp->SetObjectField(TEXT("result"), ResultData);
	return Resp;
}
