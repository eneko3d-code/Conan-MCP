#include "ConanMCPToolRegistry.h"
#include "ConanMCPTool.h"
#include "ConanMCPSettings.h"
#include "ConanMCPModule.h"
#include "HAL/PlatformTime.h"

// Forward declarations of tool registration functions from Tools/
void RegisterEditorTools(FConanMCPToolRegistry& Registry);
void RegisterActorTools(FConanMCPToolRegistry& Registry);
void RegisterAssetTools(FConanMCPToolRegistry& Registry);
void RegisterBlueprintTools(FConanMCPToolRegistry& Registry);
void RegisterDataTableTools(FConanMCPToolRegistry& Registry);
void RegisterSkeletonTools(FConanMCPToolRegistry& Registry);
void RegisterParticleTools(FConanMCPToolRegistry& Registry);
void RegisterConanTools(FConanMCPToolRegistry& Registry);

FConanMCPToolRegistry& FConanMCPToolRegistry::Get()
{
	static FConanMCPToolRegistry Instance;
	return Instance;
}

FConanMCPToolRegistry::FConanMCPToolRegistry()
{
}

FConanMCPToolRegistry::~FConanMCPToolRegistry()
{
	Clear();
}

void FConanMCPToolRegistry::RegisterAllDefaultTools()
{
	FScopeLock Lock(&RegistryLock);
	Clear();

	RegisterEditorTools(*this);
	RegisterActorTools(*this);
	RegisterAssetTools(*this);
	RegisterBlueprintTools(*this);
	RegisterDataTableTools(*this);
	RegisterSkeletonTools(*this);
	RegisterParticleTools(*this);
	RegisterConanTools(*this);

	UE_LOG(LogConanMCP, Log, TEXT("ConanMCP: Registered %d default tools across 8 categories"), RegisteredTools.Num());
}

bool FConanMCPToolRegistry::RegisterTool(TSharedPtr<IConanMCPTool> Tool)
{
	if (!Tool.IsValid()) return false;
	FString Name = Tool->GetName();
	if (Name.IsEmpty()) return false;

	FScopeLock Lock(&RegistryLock);
	RegisteredTools.Add(Name, Tool);
	return true;
}

bool FConanMCPToolRegistry::UnregisterTool(const FString& ToolName)
{
	FScopeLock Lock(&RegistryLock);
	return RegisteredTools.Remove(ToolName) > 0;
}

TSharedPtr<IConanMCPTool> FConanMCPToolRegistry::FindTool(const FString& ToolName) const
{
	FScopeLock Lock(&RegistryLock);
	if (const TSharedPtr<IConanMCPTool>* Found = RegisteredTools.Find(ToolName))
	{
		return *Found;
	}
	return nullptr;
}

TArray<TSharedPtr<IConanMCPTool>> FConanMCPToolRegistry::GetAllTools() const
{
	FScopeLock Lock(&RegistryLock);
	TArray<TSharedPtr<IConanMCPTool>> List;
	RegisteredTools.GenerateValueArray(List);
	return List;
}

TArray<TSharedPtr<FJsonValue>> FConanMCPToolRegistry::GetToolsJsonList() const
{
	FScopeLock Lock(&RegistryLock);
	TArray<TSharedPtr<FJsonValue>> List;

	for (const auto& Pair : RegisteredTools)
	{
		if (Pair.Value.IsValid())
		{
			List.Add(MakeShared<FJsonValueObject>(Pair.Value->ToMcpToolJson()));
		}
	}
	return List;
}

void FConanMCPToolRegistry::Clear()
{
	FScopeLock Lock(&RegistryLock);
	RegisteredTools.Empty();
}

bool FConanMCPToolRegistry::ValidateSecurity(const FString& ToolName, const TSharedPtr<FJsonObject>& Arguments, FString& OutErrorMessage)
{
	if (!Arguments.IsValid()) return true;

	// Check for dangerous keywords or OS injection attempts in argument strings
	static const TArray<FString> ForbiddenPatterns = {
		TEXT("cmd.exe"), TEXT("powershell"), TEXT("powershell.exe"),
		TEXT("bash.exe"), TEXT("wscript.exe"), TEXT("cscript.exe"),
		TEXT("rundll32.exe"), TEXT(".dll"), TEXT(".bat"), TEXT(".cmd"),
		TEXT(".ps1"), TEXT(".vbs"), TEXT(".exe"), TEXT("http://"), TEXT("https://")
	};

	// Helper lambda to scan all string fields in JSON recursively
	TFunction<bool(const TSharedPtr<FJsonObject>&)> ScanObject;
	ScanObject = [&](const TSharedPtr<FJsonObject>& Obj) -> bool
	{
		for (const auto& Pair : Obj->Values)
		{
			if (Pair.Value->Type == EJson::String)
			{
				FString Val = Pair.Value->AsString().ToLower();
				for (const FString& Pattern : ForbiddenPatterns)
				{
					// If a path contains .exe or powershell etc, block it
					if (Val.Contains(Pattern))
					{
						OutErrorMessage = FString::Printf(TEXT("Security violation: argument '%s' contains forbidden pattern '%s'"), *Pair.Key, *Pattern);
						return false;
					}
				}
			}
			else if (Pair.Value->Type == EJson::Object)
			{
				if (!ScanObject(Pair.Value->AsObject())) return false;
			}
		}
		return true;
	};

	return ScanObject(Arguments);
}

FConanMCPToolResult FConanMCPToolRegistry::ExecuteTool(const FString& ToolName, const TSharedPtr<FJsonObject>& Arguments)
{
	check(IsInGameThread());

	TSharedPtr<IConanMCPTool> Tool = FindTool(ToolName);
	if (!Tool.IsValid())
	{
		return FConanMCPToolResult::Error(FString::Printf(TEXT("Tool not found: '%s'"), *ToolName), -32601);
	}

	const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();

	// Security level verification
	if (Tool->GetSecurityLevel() == EConanMCPSecurityLevel::SafeWrite)
	{
		if (Settings && !Settings->bEnableWriteTools)
		{
			return FConanMCPToolResult::Error(TEXT("Security violation: SAFE_WRITE tools are disabled in ConanMCP settings"), -32000);
		}
	}
	else if (Tool->GetSecurityLevel() == EConanMCPSecurityLevel::Destructive)
	{
		if (Settings && !Settings->bEnableDestructiveTools)
		{
			return FConanMCPToolResult::Error(TEXT("Security violation: DESTRUCTIVE tools are disabled in ConanMCP settings"), -32000);
		}
	}

	// Security argument sanitization
	FString SecurityError;
	if (!ValidateSecurity(ToolName, Arguments, SecurityError))
	{
		UE_LOG(LogConanMCP, Warning, TEXT("ConanMCP Security Blocked: %s for tool %s"), *SecurityError, *ToolName);
		return FConanMCPToolResult::Error(SecurityError, -32000);
	}

	double StartTime = FPlatformTime::Seconds();

	if (Settings && Settings->bEnableLogging)
	{
		UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: Tool called: %s"), *ToolName);
	}

	FConanMCPToolResult Result = Tool->Execute(Arguments);

	double ElapsedMs = (FPlatformTime::Seconds() - StartTime) * 1000.0;
	if (Settings && Settings->bEnableLogging)
	{
		UE_LOG(LogConanMCP, Log, TEXT("LogConanMCP: Tool completed in %.1f ms (Status: %s)"), ElapsedMs, Result.bSuccess ? TEXT("OK") : TEXT("ERROR"));
	}

	return Result;
}
