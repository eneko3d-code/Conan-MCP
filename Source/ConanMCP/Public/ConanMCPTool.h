#pragma once

#include "CoreMinimal.h"
#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "Serialization/JsonSerializer.h"

/**
 * Security classifications for MCP tools.
 */
enum class EConanMCPSecurityLevel : uint8
{
	/** Read-only inspection (safe, no editor state changes). */
	ReadOnly = 0,

	/** Safe write operations with Undo/Redo transactions (e.g. transforms, attachments). */
	SafeWrite,

	/** Potentially destructive operations (e.g. deletion, bulk modifications). */
	Destructive
};

/**
 * Result structure returned by tool executions.
 */
struct FConanMCPToolResult
{
	bool bSuccess = true;
	FString ErrorMessage;
	int32 ErrorCode = 0; // JSON-RPC 2.0 error code if applicable
	TSharedPtr<FJsonObject> ResultData;

	static FConanMCPToolResult Success(TSharedPtr<FJsonObject> InData = nullptr)
	{
		FConanMCPToolResult Result;
		Result.bSuccess = true;
		Result.ResultData = InData.IsValid() ? InData : MakeShared<FJsonObject>();
		return Result;
	}

	static FConanMCPToolResult Error(const FString& Message, int32 Code = -32603)
	{
		FConanMCPToolResult Result;
		Result.bSuccess = false;
		Result.ErrorMessage = Message;
		Result.ErrorCode = Code;
		Result.ResultData = MakeShared<FJsonObject>();
		Result.ResultData->SetStringField(TEXT("error"), Message);
		return Result;
	}
};

/**
 * Abstract interface for all ConanMCP tools.
 */
class CONANMCP_API IConanMCPTool
{
public:
	virtual ~IConanMCPTool() = default;

	/** Unique identifier for the tool (e.g. "get_selected_actors"). */
	virtual FString GetName() const = 0;

	/** Category of the tool (e.g. "Editor", "Actors", "Assets", "Skeleton", "Particles", "Conan"). */
	virtual FString GetCategory() const = 0;

	/** Detailed description of what the tool does, provided to LLM clients. */
	virtual FString GetDescription() const = 0;

	/** JSON Schema object declaring all accepted and required parameters. */
	virtual TSharedPtr<FJsonObject> GetInputSchema() const = 0;

	/** Security level of the tool. */
	virtual EConanMCPSecurityLevel GetSecurityLevel() const = 0;

	/**
	 * Execute the tool with given arguments.
	 * NOTE: Guaranteed to be called on Game Thread.
	 */
	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) = 0;

	/** Formats the tool representation for the tools/list MCP method. */
	virtual TSharedPtr<FJsonObject> ToMcpToolJson() const
	{
		TSharedPtr<FJsonObject> ToolObj = MakeShared<FJsonObject>();
		ToolObj->SetStringField(TEXT("name"), GetName());
		ToolObj->SetStringField(TEXT("description"), FString::Printf(TEXT("[%s][%s] %s"), 
			*GetCategory(),
			GetSecurityLevel() == EConanMCPSecurityLevel::ReadOnly ? TEXT("READ_ONLY") :
			(GetSecurityLevel() == EConanMCPSecurityLevel::SafeWrite ? TEXT("SAFE_WRITE") : TEXT("DESTRUCTIVE")),
			*GetDescription()));
		ToolObj->SetObjectField(TEXT("inputSchema"), GetInputSchema());
		return ToolObj;
	}
};
