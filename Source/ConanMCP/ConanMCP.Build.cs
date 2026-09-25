using UnrealBuildTool;

public class ConanMCP : ModuleRules
{
	public ConanMCP(ReadOnlyTargetRules Target) : base(Target)
	{
		PCHUsage = PCHUsageMode.UseExplicitOrSharedPCHs;
		bEnableExceptions = true;

		PublicIncludePaths.AddRange(
			new string[] {
				// Public includes
			}
		);

		PrivateIncludePaths.AddRange(
			new string[] {
				// Private includes
			}
		);

		PublicDependencyModuleNames.AddRange(
			new string[]
			{
				"Core",
				"CoreUObject",
				"Engine",
				"InputCore",
				"Json",
				"JsonUtilities",
				"HTTP",
				"HTTPServer",
				"AssetRegistry",
				"Projects",
				"DeveloperSettings"
			}
		);

		PrivateDependencyModuleNames.AddRange(
			new string[]
			{
				"Slate",
				"SlateCore",
				"UnrealEd",
				"LevelEditor",
				"ToolMenus",
				"WorkspaceMenuStructure",
				"EditorSubsystem",
				"BlueprintGraph",
				"Kismet",
				"Niagara"
			}
		);

		DynamicallyLoadedModuleNames.AddRange(
			new string[]
			{
			}
		);
	}
}
