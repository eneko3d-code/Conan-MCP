#include "ConanMCPSettings.h"
#include "ConanMCPServer.h"
#include "ConanMCPModule.h"

#define LOCTEXT_NAMESPACE "ConanMCP"

UConanMCPSettings::UConanMCPSettings()
{
	bEnableServer = true;
	bAutoStartServer = true;
	BindAddress = TEXT("127.0.0.1");
	Port = 8123;
	EndpointPath = TEXT("/mcp");
	bEnableWriteTools = true;
	bEnableDestructiveTools = false;
	bEnableLogging = true;
	MaxAssetSearchResults = 50;
	CommandTimeoutSeconds = 30.0f;
}

#if WITH_EDITOR
FText UConanMCPSettings::GetSectionText() const
{
	return LOCTEXT("ConanMCPSettingsSection", "Conan MCP");
}

FText UConanMCPSettings::GetSectionDescription() const
{
	return LOCTEXT("ConanMCPSettingsDescription", "Configure the Conan MCP server settings, security permissions, and endpoints.");
}

void UConanMCPSettings::PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent)
{
	Super::PostEditChangeProperty(PropertyChangedEvent);

	const FName PropertyName = (PropertyChangedEvent.Property != nullptr) ? PropertyChangedEvent.Property->GetFName() : NAME_None;

	if (PropertyName == GET_MEMBER_NAME_CHECKED(UConanMCPSettings, Port) ||
		PropertyName == GET_MEMBER_NAME_CHECKED(UConanMCPSettings, BindAddress))
	{
		if (FConanMCPServer::Get().IsRunning())
		{
			UE_LOG(LogConanMCP, Log, TEXT("ConanMCP: Configuration changed, restarting server on %s:%d"), *BindAddress, Port);
			FConanMCPServer::Get().RestartServer();
		}
	}
	else if (PropertyName == GET_MEMBER_NAME_CHECKED(UConanMCPSettings, bEnableServer))
	{
		if (bEnableServer && !FConanMCPServer::Get().IsRunning())
		{
			FConanMCPServer::Get().StartServer(BindAddress, Port);
		}
		else if (!bEnableServer && FConanMCPServer::Get().IsRunning())
		{
			FConanMCPServer::Get().StopServer();
		}
	}
}
#endif

#undef LOCTEXT_NAMESPACE
