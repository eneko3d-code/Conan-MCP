using UnrealBuildTool;

// Optional editor-only helpers used by the ConanMCP Python server (native landscape sculpting,
// layer painting, exact Blueprint details and compiler messages). Enable it by adding the
// module to ConanMCP.uplugin (see docs/native_module.md). Python detects it automatically.
public class ConanMCPNative : ModuleRules
{
	public ConanMCPNative(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;

		PublicDependencyModuleNames.AddRange(new string[] { "Core", "CoreUObject", "Engine" });

		PrivateDependencyModuleNames.AddRange(new string[]
		{
			"UnrealEd",
			"Landscape",
			"Json",
			"BlueprintGraph",
		});
	}
}
