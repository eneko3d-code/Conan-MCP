#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "HAL/Runnable.h"
#include "HAL/RunnableThread.h"
#include "Sockets.h"
#include "SocketSubsystem.h"
#include "Interfaces/IPv4/IPv4Endpoint.h"

/**
 * High-performance, secure MCP (Model Context Protocol) HTTP/JSON-RPC 2.0 Server.
 * Listens on 127.0.0.1:8123 (configurable) and exposes the /mcp endpoint.
 */
class CONANMCP_API FConanMCPServer : public FRunnable
{
public:
	static FConanMCPServer& Get();

	FConanMCPServer();
	virtual ~FConanMCPServer();

	/** Start the server on the configured address and port. */
	bool StartServer(const FString& InBindAddress = TEXT("127.0.0.1"), int32 InPort = 8123);

	/** Stop the server and close all sockets. */
	void StopServer();

	/** Restart the server. */
	bool RestartServer();

	/** Status queries */
	bool IsRunning() const { return bIsRunning; }
	FString GetBindAddress() const { return BindAddress; }
	int32 GetPort() const { return Port; }
	FString GetEndpointUrl() const { return FString::Printf(TEXT("http://%s:%d/mcp"), *BindAddress, Port); }
	int32 GetTotalRequests() const { return TotalRequests; }
	int32 GetTotalErrors() const { return TotalErrors; }
	int32 GetConnectedClients() const { return ConnectedClients; }

	/** Process raw JSON-RPC 2.0 string request and produce JSON-RPC response. */
	FString ProcessJsonRpc(const FString& RequestJsonStr);

	// FRunnable interface
	virtual bool Init() override;
	virtual uint32 Run() override;
	virtual void Stop() override;
	virtual void Exit() override;

private:
	/** Handles an individual HTTP client connection. */
	void HandleClient(FSocket* ClientSocket);

	/** Handles JSON-RPC methods */
	TSharedPtr<FJsonObject> HandleInitialize(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal);
	TSharedPtr<FJsonObject> HandlePing(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal);
	TSharedPtr<FJsonObject> HandleToolsList(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal);
	TSharedPtr<FJsonObject> HandleToolsCall(const TSharedPtr<FJsonObject>& RequestObj, const TSharedPtr<FJsonValue>& IdVal);

	/** Helper to build JSON-RPC error responses */
	TSharedPtr<FJsonObject> MakeErrorResponse(const TSharedPtr<FJsonValue>& IdVal, int32 Code, const FString& Message);

	/** Helper to build JSON-RPC success responses */
	TSharedPtr<FJsonObject> MakeSuccessResponse(const TSharedPtr<FJsonValue>& IdVal, const TSharedPtr<FJsonObject>& ResultData);

	FString BindAddress = TEXT("127.0.0.1");
	int32 Port = 8123;
	FThreadSafeBool bIsRunning = false;
	FThreadSafeBool bStopping = false;

	FSocket* ListenerSocket = nullptr;
	FRunnableThread* Thread = nullptr;

	FThreadSafeCounter TotalRequests;
	FThreadSafeCounter TotalErrors;
	FThreadSafeCounter ConnectedClients;

	FCriticalSection ServerLock;
};
