#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "ConanMCPSettings.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "AssetRegistry/ARFilter.h"
#include "UObject/Package.h"
#include "UObject/SavePackage.h"
#include "FileHelpers.h"

// ============================================================================
// Tool: find_assets
// ============================================================================
class FFindAssetsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_assets"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Searches project assets using the AssetRegistry without loading them into memory. Returns asset names, paths, and classes."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

		TSharedPtr<FJsonObject> ClassFilter = MakeShared<FJsonObject>();
		ClassFilter->SetStringField(TEXT("type"), TEXT("string"));
		ClassFilter->SetStringField(TEXT("description"), TEXT("Asset class name (e.g. 'Blueprint', 'StaticMesh', 'ParticleSystem', 'NiagaraSystem', 'DataTable')"));
		Props->SetObjectField(TEXT("class_name"), ClassFilter);

		TSharedPtr<FJsonObject> PathFilter = MakeShared<FJsonObject>();
		PathFilter->SetStringField(TEXT("type"), TEXT("string"));
		PathFilter->SetStringField(TEXT("description"), TEXT("Package path prefix (e.g. '/Game/', '/ConanSandbox/')"));
		Props->SetObjectField(TEXT("package_path"), PathFilter);

		TSharedPtr<FJsonObject> NameFilter = MakeShared<FJsonObject>();
		NameFilter->SetStringField(TEXT("type"), TEXT("string"));
		NameFilter->SetStringField(TEXT("description"), TEXT("Substring match for asset name"));
		Props->SetObjectField(TEXT("name_filter"), NameFilter);

		TSharedPtr<FJsonObject> MaxResults = MakeShared<FJsonObject>();
		MaxResults->SetStringField(TEXT("type"), TEXT("number"));
		MaxResults->SetStringField(TEXT("description"), TEXT("Maximum results to return (default 50, maximum 500)"));
		Props->SetObjectField(TEXT("max_results"), MaxResults);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;

		if (Arguments->HasField(TEXT("class_name")))
		{
			FString ClassName = Arguments->GetStringField(TEXT("class_name"));
			if (!ClassName.IsEmpty())
			{
				Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), *ClassName));
			}
		}

		if (Arguments->HasField(TEXT("package_path")))
		{
			FString PkgPath = Arguments->GetStringField(TEXT("package_path"));
			if (!PkgPath.IsEmpty())
			{
				Filter.PackagePaths.Add(*PkgPath);
			}
		}

		FString NameFilter = Arguments->GetStringField(TEXT("name_filter"));

		const UConanMCPSettings* Settings = GetDefault<UConanMCPSettings>();
		int32 DefaultLimit = Settings ? Settings->MaxAssetSearchResults : 50;
		int32 MaxResults = Arguments->HasField(TEXT("max_results")) ? FMath::Clamp((int32)Arguments->GetNumberField(TEXT("max_results")), 1, 500) : DefaultLimit;

		TArray<FAssetData> AssetList;
		AssetRegistry.GetAssets(Filter, AssetList);

		TArray<TSharedPtr<FJsonValue>> ResultsArray;
		int32 TotalMatching = 0;

		for (const FAssetData& AssetData : AssetList)
		{
			if (!NameFilter.IsEmpty() && !AssetData.AssetName.ToString().Contains(NameFilter))
			{
				continue;
			}

			TotalMatching++;

			if (ResultsArray.Num() < MaxResults)
			{
				TSharedPtr<FJsonObject> AssetObj = MakeShared<FJsonObject>();
				AssetObj->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
				AssetObj->SetStringField(TEXT("class"), AssetData.AssetClassPath.GetAssetName().ToString());
				AssetObj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
				AssetObj->SetStringField(TEXT("package_path"), AssetData.PackagePath.ToString());
				AssetObj->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());
				ResultsArray.Add(MakeShared<FJsonValueObject>(AssetObj));
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("assets"), ResultsArray);
		Data->SetNumberField(TEXT("returned_count"), ResultsArray.Num());
		Data->SetNumberField(TEXT("total_matching"), TotalMatching);
		Data->SetNumberField(TEXT("max_results_limit"), MaxResults);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_asset_info
// ============================================================================
class FGetAssetInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_asset_info"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Returns detailed metadata and tags for a given asset path from the Asset Registry."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Full asset path or package name (e.g. '/Game/Characters/BP_Hero')"));
		Props->SetObjectField(TEXT("asset_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("asset_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString AssetPath = Arguments->GetStringField(TEXT("asset_path"));
		FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(AssetPath));

		if (!AssetData.IsValid())
		{
			// Try by package name
			TArray<FAssetData> PkgAssets;
			AssetRegistry.GetAssetsByPackageName(*AssetPath, PkgAssets);
			if (PkgAssets.Num() > 0)
			{
				AssetData = PkgAssets[0];
			}
		}

		if (!AssetData.IsValid())
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Asset not found at path: %s"), *AssetPath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), AssetData.AssetName.ToString());
		Data->SetStringField(TEXT("class"), AssetData.AssetClassPath.GetAssetName().ToString());
		Data->SetStringField(TEXT("class_path"), AssetData.AssetClassPath.ToString());
		Data->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
		Data->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());

		TSharedPtr<FJsonObject> TagsObj = MakeShared<FJsonObject>();
		AssetData.TagsAndValues.ForEach([&TagsObj](const TPair<FName, FAssetTagValueRef>& Pair)
		{
			TagsObj->SetStringField(Pair.Key.ToString(), Pair.Value.AsString());
		});
		Data->SetObjectField(TEXT("tags"), TagsObj);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_asset_class
// ============================================================================
class FGetAssetClassTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_asset_class"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Returns the class of an asset given its package path."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Asset object path"));
		Props->SetObjectField(TEXT("asset_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("asset_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
		FString AssetPath = Arguments->GetStringField(TEXT("asset_path"));
		FAssetData AssetData = AssetRegistry.GetAssetByObjectPath(FSoftObjectPath(AssetPath));

		if (!AssetData.IsValid())
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Asset not found at '%s'"), *AssetPath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("asset_name"), AssetData.AssetName.ToString());
		Data->SetStringField(TEXT("class_name"), AssetData.AssetClassPath.GetAssetName().ToString());
		Data->SetStringField(TEXT("class_path"), AssetData.AssetClassPath.ToString());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_asset_path
// ============================================================================
class FGetAssetPathTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_asset_path"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Resolves an asset name to its full package and disk path."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> NameProp = MakeShared<FJsonObject>();
		NameProp->SetStringField(TEXT("type"), TEXT("string"));
		NameProp->SetStringField(TEXT("description"), TEXT("Asset name (without path)"));
		Props->SetObjectField(TEXT("asset_name"), NameProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("asset_name")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
		FString AssetName = Arguments->GetStringField(TEXT("asset_name"));

		TArray<FAssetData> Matches;
		FARFilter Filter;
		Filter.bRecursivePaths = true;
		AssetRegistry.GetAssets(Filter, Matches);

		TArray<TSharedPtr<FJsonValue>> PathsList;
		for (const FAssetData& AssetData : Matches)
		{
			if (AssetData.AssetName.ToString().Equals(AssetName, ESearchCase::IgnoreCase))
			{
				TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
				Obj->SetStringField(TEXT("package_name"), AssetData.PackageName.ToString());
				Obj->SetStringField(TEXT("object_path"), AssetData.GetObjectPathString());
				Obj->SetStringField(TEXT("class"), AssetData.AssetClassPath.GetAssetName().ToString());
				PathsList.Add(MakeShared<FJsonValueObject>(Obj));
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("query_name"), AssetName);
		Data->SetArrayField(TEXT("matches"), PathsList);
		Data->SetNumberField(TEXT("count"), PathsList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_asset_dependencies
// ============================================================================
class FGetAssetDependenciesTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_asset_dependencies"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Queries direct dependencies and referencers of an asset package via the Asset Registry."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PkgProp = MakeShared<FJsonObject>();
		PkgProp->SetStringField(TEXT("type"), TEXT("string"));
		PkgProp->SetStringField(TEXT("description"), TEXT("Package name (e.g. '/Game/Characters/Hero')"));
		Props->SetObjectField(TEXT("package_name"), PkgProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("package_name")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();
		FString PackageName = Arguments->GetStringField(TEXT("package_name"));

		TArray<FName> Dependencies;
		AssetRegistry.GetDependencies(*PackageName, Dependencies, UE::AssetRegistry::EDependencyCategory::Package);

		TArray<FName> Referencers;
		AssetRegistry.GetReferencers(*PackageName, Referencers, UE::AssetRegistry::EDependencyCategory::Package);

		TArray<TSharedPtr<FJsonValue>> DepList;
		for (const FName& Dep : Dependencies)
		{
			DepList.Add(MakeShared<FJsonValueString>(Dep.ToString()));
		}

		TArray<TSharedPtr<FJsonValue>> RefList;
		for (const FName& Ref : Referencers)
		{
			RefList.Add(MakeShared<FJsonValueString>(Ref.ToString()));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("package_name"), PackageName);
		Data->SetArrayField(TEXT("dependencies"), DepList);
		Data->SetArrayField(TEXT("referencers"), RefList);
		Data->SetNumberField(TEXT("dependency_count"), DepList.Num());
		Data->SetNumberField(TEXT("referencer_count"), RefList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: save_asset
// ============================================================================
class FSaveAssetTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("save_asset"); }
	virtual FString GetCategory() const override { return TEXT("Assets"); }
	virtual FString GetDescription() const override { return TEXT("Saves a specific package/asset to disk."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::SafeWrite; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PkgProp = MakeShared<FJsonObject>();
		PkgProp->SetStringField(TEXT("type"), TEXT("string"));
		PkgProp->SetStringField(TEXT("description"), TEXT("Package name to save (e.g. '/Game/Data/ItemTable')"));
		Props->SetObjectField(TEXT("package_name"), PkgProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("package_name")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString PackageName = Arguments->GetStringField(TEXT("package_name"));
		UPackage* Package = FindPackage(nullptr, *PackageName);
		if (!Package)
		{
			Package = LoadPackage(nullptr, *PackageName, LOAD_None);
		}

		if (!Package)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Package '%s' could not be loaded or found"), *PackageName));
		}

		TArray<UPackage*> PackagesToSave;
		PackagesToSave.Add(Package);
		bool bSaved = UEditorLoadingAndSavingUtils::SavePackages(PackagesToSave, false);

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("package_name"), PackageName);
		Data->SetBoolField(TEXT("saved"), bSaved);

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterAssetTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FFindAssetsTool>());
	Registry.RegisterTool(MakeShared<FGetAssetInfoTool>());
	Registry.RegisterTool(MakeShared<FGetAssetClassTool>());
	Registry.RegisterTool(MakeShared<FGetAssetPathTool>());
	Registry.RegisterTool(MakeShared<FGetAssetDependenciesTool>());
	Registry.RegisterTool(MakeShared<FSaveAssetTool>());
}
