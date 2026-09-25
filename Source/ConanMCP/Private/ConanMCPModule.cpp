#include "ConanMCPModule.h"
#include "ConanMCPServer.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPSettings.h"
#include "Framework/Docking/TabManager.h"
#include "Widgets/Docking/SDockTab.h"
#include "Widgets/Text/STextBlock.h"
#include "Widgets/Input/SButton.h"
#include "Widgets/Layout/SBox.h"
#include "Widgets/Layout/SBorder.h"
#include "Widgets/SBoxPanel.h"
#include "HAL/IConsoleManager.h"
#include "HAL/PlatformApplicationMisc.h"
#include "WorkspaceMenuStructure.h"
#include "WorkspaceMenuStructureModule.h"

DEFINE_LOG_CATEGORY(LogConanMCP);

#define LOCTEXT_NAMESPACE "ConanMCP"

static const FName ConanMCPTabName("ConanMCPDashboard");

void FConanMCPModule::StartupModule()
{
	UE_LOG(LogConanMCP, Log, TEXT("ConanMCP: Initializing ConanMCP module for UE 5.8.2..."));

	// Register all tools
	FConanMCPToolRegistry::Get().RegisterAllDefaultTools();

	// Register console commands
	RegisterConsoleCommands();

	// Register UI tab
	RegisterEditorUI();

	// Auto-start server if enabled in settings
	const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();
	if (Settings && Settings->bEnableServer && Settings->bAutoStartServer)
	{
		FConanMCPServer::Get().StartServer(Settings->BindAddress, Settings->Port);
	}
}

void FConanMCPModule::ShutdownModule()
{
	UE_LOG(LogConanMCP, Log, TEXT("ConanMCP: Shutting down ConanMCP module..."));

	// Stop server
	FConanMCPServer::Get().StopServer();

	// Unregister UI & commands
	UnregisterEditorUI();
	UnregisterConsoleCommands();

	// Clear tools
	FConanMCPToolRegistry::Get().Clear();
}

void FConanMCPModule::RegisterConsoleCommands()
{
	ConsoleCommands.Add(IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("ConanMCP.Start"),
		TEXT("Starts the ConanMCP server. Usage: ConanMCP.Start [Port]"),
		FConsoleCommandWithArgsDelegate::CreateRaw(this, &FConanMCPModule::Command_StartServer),
		ECVF_Default
	));

	ConsoleCommands.Add(IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("ConanMCP.Stop"),
		TEXT("Stops the ConanMCP server."),
		FConsoleCommandWithArgsDelegate::CreateRaw(this, &FConanMCPModule::Command_StopServer),
		ECVF_Default
	));

	ConsoleCommands.Add(IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("ConanMCP.Status"),
		TEXT("Prints current ConanMCP server status and statistics."),
		FConsoleCommandWithArgsDelegate::CreateRaw(this, &FConanMCPModule::Command_Status),
		ECVF_Default
	));

	ConsoleCommands.Add(IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("ConanMCP.ListTools"),
		TEXT("Lists all registered ConanMCP tools and security levels."),
		FConsoleCommandWithArgsDelegate::CreateRaw(this, &FConanMCPModule::Command_ListTools),
		ECVF_Default
	));

	ConsoleCommands.Add(IConsoleManager::Get().RegisterConsoleCommand(
		TEXT("ConanMCP.ReloadTools"),
		TEXT("Reloads and re-registers all default tools."),
		FConsoleCommandWithArgsDelegate::CreateRaw(this, &FConanMCPModule::Command_ReloadTools),
		ECVF_Default
	));
}

void FConanMCPModule::UnregisterConsoleCommands()
{
	for (IConsoleCommand* Cmd : ConsoleCommands)
	{
		if (Cmd)
		{
			IConsoleManager::Get().UnregisterConsoleObject(Cmd);
		}
	}
	ConsoleCommands.Empty();
}

void FConanMCPModule::Command_StartServer(const TArray<FString>& Args)
{
	const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();
	FString Address = Settings ? Settings->BindAddress : TEXT("127.0.0.1");
	int32 Port = Settings ? Settings->Port : 8123;

	if (Args.Num() > 0)
	{
		Port = FCString::Atoi(*Args[0]);
		if (Port <= 0) Port = 8123;
	}

	FConanMCPServer::Get().StartServer(Address, Port);
}

void FConanMCPModule::Command_StopServer(const TArray<FString>& Args)
{
	FConanMCPServer::Get().StopServer();
}

void FConanMCPModule::Command_Status(const TArray<FString>& Args)
{
	const FConanMCPServer& Server = FConanMCPServer::Get();
	UE_LOG(LogConanMCP, Log, TEXT("================ ConanMCP Status ================"));
	UE_LOG(LogConanMCP, Log, TEXT("Running:            %s"), Server.IsRunning() ? TEXT("YES") : TEXT("NO"));
	UE_LOG(LogConanMCP, Log, TEXT("Address:            %s"), *Server.GetEndpointUrl());
	UE_LOG(LogConanMCP, Log, TEXT("Registered Tools:   %d"), FConanMCPToolRegistry::Get().GetToolCount());
	UE_LOG(LogConanMCP, Log, TEXT("Connected Clients:  %d"), Server.GetConnectedClients());
	UE_LOG(LogConanMCP, Log, TEXT("Total Requests:     %d"), Server.GetTotalRequests());
	UE_LOG(LogConanMCP, Log, TEXT("Total Errors:       %d"), Server.GetTotalErrors());
	UE_LOG(LogConanMCP, Log, TEXT("================================================="));
}

void FConanMCPModule::Command_ListTools(const TArray<FString>& Args)
{
	TArray<TSharedPtr<IConanMCPTool>> Tools = FConanMCPToolRegistry::Get().GetAllTools();
	UE_LOG(LogConanMCP, Log, TEXT("================ ConanMCP Registered Tools (%d) ================"), Tools.Num());
	for (const auto& Tool : Tools)
	{
		if (Tool.IsValid())
		{
			FString SecStr = Tool->GetSecurityLevel() == EConanMCPSecurityLevel::ReadOnly ? TEXT("READ_ONLY") :
				(Tool->GetSecurityLevel() == EConanMCPSecurityLevel::SafeWrite ? TEXT("SAFE_WRITE") : TEXT("DESTRUCTIVE"));
			UE_LOG(LogConanMCP, Log, TEXT("  - %-30s [%-11s] (%s) : %s"), *Tool->GetName(), *SecStr, *Tool->GetCategory(), *Tool->GetDescription());
		}
	}
	UE_LOG(LogConanMCP, Log, TEXT("================================================================="));
}

void FConanMCPModule::Command_ReloadTools(const TArray<FString>& Args)
{
	FConanMCPToolRegistry::Get().RegisterAllDefaultTools();
	UE_LOG(LogConanMCP, Log, TEXT("ConanMCP: Tools reloaded. Total: %d"), FConanMCPToolRegistry::Get().GetToolCount());
}

void FConanMCPModule::RegisterEditorUI()
{
	FGlobalTabmanager::Get()->RegisterNomadTabSpawner(
		ConanMCPTabName,
		FOnSpawnTab::CreateRaw(this, &FConanMCPModule::OnSpawnPluginTab)
	)
	.SetDisplayName(LOCTEXT("ConanMCPTabTitle", "Conan MCP"))
	.SetMenuType(ETabSpawnerType::Hidden)
	.SetGroup(WorkspaceMenu::GetMenuStructure().GetDeveloperToolsMiscCategory());
}

void FConanMCPModule::UnregisterEditorUI()
{
	FGlobalTabmanager::Get()->UnregisterNomadTabSpawner(ConanMCPTabName);
}

TSharedRef<SDockTab> FConanMCPModule::OnSpawnPluginTab(const FSpawnTabArgs& SpawnTabArgs)
{
	return SNew(SDockTab)
		.TabRole(ETabRole::NomadTab)
		[
			SNew(SBorder)
			.Padding(16.0f)
			[
				SNew(SVerticalBox)

				// Header
				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 0, 0, 16)
				[
					SNew(STextBlock)
					.Text(LOCTEXT("ConanMCPTitle", "Conan MCP Server Dashboard"))
					.Font(FCoreStyle::GetDefaultFontStyle("Bold", 16))
				]

				// Status details
				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text(LOCTEXT("StatusLabel", "Server Status: ")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text_Lambda([]()
						{
							return FConanMCPServer::Get().IsRunning()
								? LOCTEXT("StatusRunning", "[Running] Online")
								: LOCTEXT("StatusStopped", "[Stopped] Offline");
						})
					]
				]

				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text(LOCTEXT("AddressLabel", "Endpoint URL: ")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text_Lambda([]()
						{
							return FText::FromString(FConanMCPServer::Get().GetEndpointUrl());
						})
					]
				]

				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text(LOCTEXT("ToolsCountLabel", "Registered Tools: ")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text_Lambda([]()
						{
							return FText::AsNumber(FConanMCPToolRegistry::Get().GetToolCount());
						})
					]
				]

				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text(LOCTEXT("RequestsLabel", "Total Requests: ")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text_Lambda([]()
						{
							return FText::AsNumber(FConanMCPServer::Get().GetTotalRequests());
						})
					]
				]

				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 4)
				[
					SNew(SHorizontalBox)
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text(LOCTEXT("ErrorsLabel", "Total Errors: ")).Font(FCoreStyle::GetDefaultFontStyle("Bold", 10))
					]
					+ SHorizontalBox::Slot().AutoWidth()
					[
						SNew(STextBlock).Text_Lambda([]()
						{
							return FText::AsNumber(FConanMCPServer::Get().GetTotalErrors());
						})
					]
				]

				// Action buttons
				+ SVerticalBox::Slot()
				.AutoHeight()
				.Padding(0, 16, 0, 0)
				[
					SNew(SHorizontalBox)

					+ SHorizontalBox::Slot()
					.AutoWidth()
					.Padding(0, 0, 8, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("StartServerBtn", "Start Server"))
						.IsEnabled_Lambda([]() { return !FConanMCPServer::Get().IsRunning(); })
						.OnClicked_Lambda([]()
						{
							const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();
							FConanMCPServer::Get().StartServer(Settings ? Settings->BindAddress : TEXT("127.0.0.1"), Settings ? Settings->Port : 8123);
							return FReply::Handled();
						})
					]

					+ SHorizontalBox::Slot()
					.AutoWidth()
					.Padding(0, 0, 8, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("StopServerBtn", "Stop Server"))
						.IsEnabled_Lambda([]() { return FConanMCPServer::Get().IsRunning(); })
						.OnClicked_Lambda([]()
						{
							FConanMCPServer::Get().StopServer();
							return FReply::Handled();
						})
					]

					+ SHorizontalBox::Slot()
					.AutoWidth()
					.Padding(0, 0, 8, 0)
					[
						SNew(SButton)
						.Text(LOCTEXT("CopyUrlBtn", "Copy MCP URL"))
						.OnClicked_Lambda([]()
						{
							FPlatformApplicationMisc::ClipboardCopy(*FConanMCPServer::Get().GetEndpointUrl());
							return FReply::Handled();
						})
					]
				]
			]
		];
}

#undef LOCTEXT_NAMESPACE

IMPLEMENT_MODULE(FConanMCPModule, ConanMCP)
