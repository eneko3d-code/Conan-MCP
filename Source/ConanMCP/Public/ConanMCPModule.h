#pragma once

#include "CoreMinimal.h"
#include "Modules/ModuleManager.h"

DECLARE_LOG_CATEGORY_EXTERN(LogConanMCP, Log, All);

/**
 * Main module interface for ConanMCP.
 */
class FConanMCPModule : public IModuleInterface
{
public:
	/** IModuleInterface implementation */
	virtual void StartupModule() override;
	virtual void ShutdownModule() override;

	static FConanMCPModule& Get()
	{
		return FModuleManager::LoadModuleChecked<FConanMCPModule>("ConanMCP");
	}

	static bool IsAvailable()
	{
		return FModuleManager::Get().IsModuleLoaded("ConanMCP");
	}

private:
	/** Registers Editor console commands */
	void RegisterConsoleCommands();
	void UnregisterConsoleCommands();

	/** Registers Slate tab and menu extension */
	void RegisterEditorUI();
	void UnregisterEditorUI();

	/** Tab spawner callback */
	TSharedRef<class SDockTab> OnSpawnPluginTab(const class FSpawnTabArgs& SpawnTabArgs);

	/** Console command callbacks */
	void Command_StartServer(const TArray<FString>& Args);
	void Command_StopServer(const TArray<FString>& Args);
	void Command_Status(const TArray<FString>& Args);
	void Command_ListTools(const TArray<FString>& Args);
	void Command_ReloadTools(const TArray<FString>& Args);

	TArray<struct IConsoleCommand*> ConsoleCommands;
	TSharedPtr<class FUICommandList> PluginCommands;
};
