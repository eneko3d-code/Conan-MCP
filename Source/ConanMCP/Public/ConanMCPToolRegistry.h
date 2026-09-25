#pragma once

#include "CoreMinimal.h"
#include "ConanMCPTool.h"

/**
 * Registry holding and managing all available ConanMCP tools.
 */
class CONANMCP_API FConanMCPToolRegistry
{
public:
	static FConanMCPToolRegistry& Get();

	FConanMCPToolRegistry();
	~FConanMCPToolRegistry();

	/** Register all default tool categories. */
	void RegisterAllDefaultTools();

	/** Register a specific tool instance. */
	bool RegisterTool(TSharedPtr<IConanMCPTool> Tool);

	/** Unregister a tool by name. */
	bool UnregisterTool(const FString& ToolName);

	/** Find tool by name. */
	TSharedPtr<IConanMCPTool> FindTool(const FString& ToolName) const;

	/** Get list of all registered tools. */
	TArray<TSharedPtr<IConanMCPTool>> GetAllTools() const;

	/** Generate the tools/list result array. */
	TArray<TSharedPtr<FJsonValue>> GetToolsJsonList() const;

	/** Number of registered tools. */
	int32 GetToolCount() const { return RegisteredTools.Num(); }

	/**
	 * Execute a tool by name.
	 * Performs security validation (SAFE_WRITE / DESTRUCTIVE / Path validation).
	 * Must be invoked on Game Thread.
	 */
	FConanMCPToolResult ExecuteTool(const FString& ToolName, const TSharedPtr<FJsonObject>& Arguments);

	/** Clears all registered tools. */
	void Clear();

private:
	/** Validates arguments against forbidden security patterns (OS commands, arbitrary DLLs, etc.). */
	bool ValidateSecurity(const FString& ToolName, const TSharedPtr<FJsonObject>& Arguments, FString& OutErrorMessage);

	TMap<FString, TSharedPtr<IConanMCPTool>> RegisteredTools;
	mutable FCriticalSection RegistryLock;
};
