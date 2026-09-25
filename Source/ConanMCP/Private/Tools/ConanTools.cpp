#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetRegistry/ARFilter.h"

// ============================================================================
// Tool: find_conan_assets
// ============================================================================
class FFindConanAssetsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_conan_assets"); }
	virtual FString GetCategory() const override { return TEXT("Conan"); }
	virtual FString GetDescription() const override { return TEXT("Searches Conan Exiles assets across /Game/ and /ConanSandbox/ content directories."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> NameProp = MakeShared<FJsonObject>();
		NameProp->SetStringField(TEXT("type"), TEXT("string"));
		NameProp->SetStringField(TEXT("description"), TEXT("Name or substring to search for"));
		Props->SetObjectField(TEXT("query"), NameProp);

		TSharedPtr<FJsonObject> ClassProp = MakeShared<FJsonObject>();
		ClassProp->SetStringField(TEXT("type"), TEXT("string"));
		ClassProp->SetStringField(TEXT("description"), TEXT("Optional class filter"));
		Props->SetObjectField(TEXT("class_name"), ClassProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString Query = Arguments->GetStringField(TEXT("query"));
		FString ClassName = Arguments->GetStringField(TEXT("class_name"));

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.PackagePaths.Add(TEXT("/Game"));
		Filter.PackagePaths.Add(TEXT("/ConanSandbox"));

		if (!ClassName.IsEmpty())
		{
			Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), *ClassName));
		}

		TArray<FAssetData> Matches;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : Matches)
		{
			if (!Query.IsEmpty() && !AssetData.AssetName.ToString().Contains(Query))
			{
				continue;
			}

			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
			Obj->SetStringField(TEXT("class"), AssetData.AssetClassPath.GetAssetName().ToString());
			Obj->SetStringField(TEXT("package"), AssetData.PackageName.ToString());
			Results.Add(MakeShared<FJsonValueObject>(Obj));

			if (Results.Num() >= 50) break;
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("assets"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: find_conan_datatables
// ============================================================================
class FFindConanDataTablesTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_conan_datatables"); }
	virtual FString GetCategory() const override { return TEXT("Conan"); }
	virtual FString GetDescription() const override { return TEXT("Searches for Conan Exiles gameplay, item, recipe, and spawn DataTables."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> QueryProp = MakeShared<FJsonObject>();
		QueryProp->SetStringField(TEXT("type"), TEXT("string"));
		QueryProp->SetStringField(TEXT("description"), TEXT("DataTable keyword (e.g. 'Item', 'Recipe', 'Spawn', 'Feat')"));
		Props->SetObjectField(TEXT("query"), QueryProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString Query = Arguments->GetStringField(TEXT("query"));

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("DataTable")));
		Filter.PackagePaths.Add(TEXT("/Game"));
		Filter.PackagePaths.Add(TEXT("/ConanSandbox"));

		TArray<FAssetData> Matches;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : Matches)
		{
			if (!Query.IsEmpty() && !AssetData.AssetName.ToString().Contains(Query))
			{
				continue;
			}

			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
			Obj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
			Obj->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());
			Results.Add(MakeShared<FJsonValueObject>(Obj));

			if (Results.Num() >= 50) break;
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("datatables"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: find_conan_characters
// ============================================================================
class FFindConanCharactersTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_conan_characters"); }
	virtual FString GetCategory() const override { return TEXT("Conan"); }
	virtual FString GetDescription() const override { return TEXT("Finds Conan Exiles character blueprints, monster templates, thralls, and NPC definitions."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> QueryProp = MakeShared<FJsonObject>();
		QueryProp->SetStringField(TEXT("type"), TEXT("string"));
		QueryProp->SetStringField(TEXT("description"), TEXT("Character name or keyword (e.g. 'Human', 'NPC', 'Monster', 'Thrall')"));
		Props->SetObjectField(TEXT("query"), QueryProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString Query = Arguments->GetStringField(TEXT("query"));

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("Blueprint")));
		Filter.PackagePaths.Add(TEXT("/Game/Characters"));
		Filter.PackagePaths.Add(TEXT("/Game"));
		Filter.PackagePaths.Add(TEXT("/ConanSandbox/Characters"));

		TArray<FAssetData> Matches;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : Matches)
		{
			FString AssetName = AssetData.AssetName.ToString();
			if (!Query.IsEmpty() && !AssetName.Contains(Query))
			{
				continue;
			}

			// Filter to character-like blueprints if no query was given
			if (Query.IsEmpty() && !AssetName.Contains(TEXT("Char")) && !AssetName.Contains(TEXT("NPC")) && !AssetName.Contains(TEXT("Monster")))
			{
				continue;
			}

			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetStringField(TEXT("name"), AssetName);
			Obj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
			Obj->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());
			Results.Add(MakeShared<FJsonValueObject>(Obj));

			if (Results.Num() >= 50) break;
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("characters"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: find_conan_items
// ============================================================================
class FFindConanItemsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_conan_items"); }
	virtual FString GetCategory() const override { return TEXT("Conan"); }
	virtual FString GetDescription() const override { return TEXT("Finds Conan Exiles items, weapons, armor, and inventory assets."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> QueryProp = MakeShared<FJsonObject>();
		QueryProp->SetStringField(TEXT("type"), TEXT("string"));
		QueryProp->SetStringField(TEXT("description"), TEXT("Item name or keyword (e.g. 'sword', 'shield', 'armor', 'bow')"));
		Props->SetObjectField(TEXT("query"), QueryProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString Query = Arguments->GetStringField(TEXT("query"));

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.PackagePaths.Add(TEXT("/Game/Items"));
		Filter.PackagePaths.Add(TEXT("/Game/Weapons"));
		Filter.PackagePaths.Add(TEXT("/Game/Armor"));
		Filter.PackagePaths.Add(TEXT("/Game"));

		TArray<FAssetData> Matches;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : Matches)
		{
			if (!Query.IsEmpty() && !AssetData.AssetName.ToString().Contains(Query))
			{
				continue;
			}

			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
			Obj->SetStringField(TEXT("class"), AssetData.AssetClassPath.GetAssetName().ToString());
			Obj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
			Results.Add(MakeShared<FJsonValueObject>(Obj));

			if (Results.Num() >= 50) break;
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("items"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: find_conan_particles
// ============================================================================
class FFindConanParticlesTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_conan_particles"); }
	virtual FString GetCategory() const override { return TEXT("Conan"); }
	virtual FString GetDescription() const override { return TEXT("Searches specifically within Conan Exiles VFX/effects libraries."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> QueryProp = MakeShared<FJsonObject>();
		QueryProp->SetStringField(TEXT("type"), TEXT("string"));
		QueryProp->SetStringField(TEXT("description"), TEXT("Effect keyword (e.g. 'blood', 'fire', 'sorcery', 'impact', 'sandstorm')"));
		Props->SetObjectField(TEXT("query"), QueryProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString Query = Arguments->GetStringField(TEXT("query"));

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("ParticleSystem")));
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Niagara"), TEXT("NiagaraSystem")));
		Filter.PackagePaths.Add(TEXT("/Game/Effects"));
		Filter.PackagePaths.Add(TEXT("/Game/VFX"));
		Filter.PackagePaths.Add(TEXT("/Game"));

		TArray<FAssetData> Matches;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : Matches)
		{
			if (!Query.IsEmpty() && !AssetData.AssetName.ToString().Contains(Query))
			{
				continue;
			}

			TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
			Obj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
			Obj->SetStringField(TEXT("type"), AssetData.AssetClassPath.GetAssetName().ToString());
			Obj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
			Obj->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());
			Results.Add(MakeShared<FJsonValueObject>(Obj));

			if (Results.Num() >= 50) break;
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("particles"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterConanTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FFindConanAssetsTool>());
	Registry.RegisterTool(MakeShared<FFindConanDataTablesTool>());
	Registry.RegisterTool(MakeShared<FFindConanCharactersTool>());
	Registry.RegisterTool(MakeShared<FFindConanItemsTool>());
	Registry.RegisterTool(MakeShared<FFindConanParticlesTool>());
}
