#pragma once

#include "CoreMinimal.h"
#include "Engine/DeveloperSettings.h"
#include "ConanMCPSettings.generated.h"

/**
 * Settings for the ConanMCP plugin.
 * Accessible in Editor via: Edit -> Editor Preferences -> Plugins -> Conan MCP
 */
UCLASS(config = EditorPerProjectUserSettings, defaultconfig, meta = (DisplayName = "Conan MCP"))
class CONANMCP_API UConanMCPSettings : public UDeveloperSettings
{
	GENERATED_BODY()

public:
	UConanMCPSettings();

	// UDeveloperSettings interface
	virtual FName GetContainerName() const override { return TEXT("Editor"); }
	virtual FName GetCategoryName() const override { return TEXT("Plugins"); }
	virtual FName GetSectionName() const override { return TEXT("ConanMCP"); }

#if WITH_EDITOR
	virtual FText GetSectionText() const override;
	virtual FText GetSectionDescription() const override;
	virtual void PostEditChangeProperty(FPropertyChangedEvent& PropertyChangedEvent) override;
#endif

public:
	/** Enable or disable the MCP server. */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (DisplayName = "Enable MCP Server"))
	bool bEnableServer = true;

	/** Automatically start the MCP server when the editor launches. */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (DisplayName = "Auto Start MCP Server"))
	bool bAutoStartServer = true;

	/**
	 * Local IP address to bind to. Default: 127.0.0.1.
	 * IMPORTANT: Do not bind to 0.0.0.0 for security reasons.
	 */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (DisplayName = "Bind Address"))
	FString BindAddress = TEXT("127.0.0.1");

	/** Port for the MCP HTTP/JSON-RPC server. Default: 8123. */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (DisplayName = "Port", ClampMin = "1024", ClampMax = "65535"))
	int32 Port = 8123;

	/** Endpoint path for the MCP server. Default: /mcp */
	UPROPERTY(config, EditAnywhere, Category = "Server", meta = (DisplayName = "Endpoint Path"))
	FString EndpointPath = TEXT("/mcp");

	/** Enable tools that perform safe write operations (e.g. setting transforms, saving levels). */
	UPROPERTY(config, EditAnywhere, Category = "Security", meta = (DisplayName = "Enable Write Tools"))
	bool bEnableWriteTools = true;

	/**
	 * Enable destructive tools (e.g. deleting actors, modifying core project settings).
	 * Must be explicitly enabled by user.
	 */
	UPROPERTY(config, EditAnywhere, Category = "Security", meta = (DisplayName = "Enable Destructive Tools"))
	bool bEnableDestructiveTools = false;

	/** Enable detailed logging in LogConanMCP. */
	UPROPERTY(config, EditAnywhere, Category = "Logging", meta = (DisplayName = "Enable Logging"))
	bool bEnableLogging = true;

	/** Default maximum number of results returned by Asset Registry searches (1 - 500). */
	UPROPERTY(config, EditAnywhere, Category = "Performance", meta = (DisplayName = "Max Asset Search Results", ClampMin = "1", ClampMax = "500"))
	int32 MaxAssetSearchResults = 50;

	/** Timeout in seconds when waiting for Game Thread operations to execute (Default: 30s). */
	UPROPERTY(config, EditAnywhere, Category = "Performance", meta = (DisplayName = "Command Timeout (Seconds)", ClampMin = "5.0", ClampMax = "120.0"))
	float CommandTimeoutSeconds = 30.0f;
};
