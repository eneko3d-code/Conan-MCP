#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Engine/Blueprint.h"
#include "Engine/BlueprintGeneratedClass.h"

// ============================================================================
// Tool: find_blueprint
// ============================================================================
class FFindBlueprintTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_blueprint"); }
	virtual FString GetCategory() const override { return TEXT("Blueprints"); }
	virtual FString GetDescription() const override { return TEXT("Searches for Blueprint assets matching a name or path filter."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> NameProp = MakeShared<FJsonObject>();
		NameProp->SetStringField(TEXT("type"), TEXT("string"));
		NameProp->SetStringField(TEXT("description"), TEXT("Blueprint name or substring (e.g. 'BP_Player')"));
		Props->SetObjectField(TEXT("name"), NameProp);

		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Optional package path prefix"));
		Props->SetObjectField(TEXT("path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("Blueprint")));

		if (Arguments->HasField(TEXT("path")))
		{
			FString Path = Arguments->GetStringField(TEXT("path"));
			if (!Path.IsEmpty())
			{
				Filter.PackagePaths.Add(*Path);
			}
		}

		FString NameQuery = Arguments->GetStringField(TEXT("name"));

		TArray<FAssetData> AssetList;
		AssetRegistry.GetAssets(Filter, AssetList);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : AssetList)
		{
			if (!NameQuery.IsEmpty() && !AssetData.AssetName.ToString().Contains(NameQuery))
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
		Data->SetArrayField(TEXT("blueprints"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_blueprint_info
// ============================================================================
class FGetBlueprintInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_blueprint_info"); }
	virtual FString GetCategory() const override { return TEXT("Blueprints"); }
	virtual FString GetDescription() const override { return TEXT("Returns parent class, generated class, and variable definitions of a Blueprint."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Blueprint asset path (e.g. '/Game/Characters/BP_Hero')"));
		Props->SetObjectField(TEXT("blueprint_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("blueprint_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString BlueprintPath = Arguments->GetStringField(TEXT("blueprint_path"));
		UBlueprint* Blueprint = LoadObject<UBlueprint>(nullptr, *BlueprintPath);
		if (!Blueprint)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load Blueprint at '%s'"), *BlueprintPath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), Blueprint->GetName());
		Data->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetName() : TEXT("None"));
		Data->SetStringField(TEXT("generated_class"), Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetName() : TEXT("None"));

		TArray<TSharedPtr<FJsonValue>> VarsList;
		for (const FBPVariableDescription& Var : Blueprint->NewVariables)
		{
			TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
			VarObj->SetStringField(TEXT("name"), Var.VarName.ToString());
			VarObj->SetStringField(TEXT("type"), Var.VarType.PinCategory.ToString());
			VarObj->SetStringField(TEXT("sub_category"), Var.VarType.PinSubCategory.ToString());
			VarsList.Add(MakeShared<FJsonValueObject>(VarObj));
		}
		Data->SetArrayField(TEXT("variables"), VarsList);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_blueprint_parent_class
// ============================================================================
class FGetBlueprintParentClassTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_blueprint_parent_class"); }
	virtual FString GetCategory() const override { return TEXT("Blueprints"); }
	virtual FString GetDescription() const override { return TEXT("Returns the direct parent class name of a Blueprint."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Blueprint asset path"));
		Props->SetObjectField(TEXT("blueprint_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("blueprint_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString BlueprintPath = Arguments->GetStringField(TEXT("blueprint_path"));
		UBlueprint* Blueprint = LoadObject<UBlueprint>(nullptr, *BlueprintPath);
		if (!Blueprint)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load Blueprint at '%s'"), *BlueprintPath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("blueprint"), Blueprint->GetName());
		Data->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetName() : TEXT("None"));
		Data->SetStringField(TEXT("parent_class_path"), Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : TEXT("None"));

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_blueprint_variables
// ============================================================================
class FGetBlueprintVariablesTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_blueprint_variables"); }
	virtual FString GetCategory() const override { return TEXT("Blueprints"); }
	virtual FString GetDescription() const override { return TEXT("Lists all declared member variables and types in a Blueprint."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Blueprint asset path"));
		Props->SetObjectField(TEXT("blueprint_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("blueprint_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString BlueprintPath = Arguments->GetStringField(TEXT("blueprint_path"));
		UBlueprint* Blueprint = LoadObject<UBlueprint>(nullptr, *BlueprintPath);
		if (!Blueprint)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load Blueprint at '%s'"), *BlueprintPath));
		}

		TArray<TSharedPtr<FJsonValue>> VarsList;
		for (const FBPVariableDescription& Var : Blueprint->NewVariables)
		{
			TSharedPtr<FJsonObject> VarObj = MakeShared<FJsonObject>();
			VarObj->SetStringField(TEXT("name"), Var.VarName.ToString());
			VarObj->SetStringField(TEXT("category"), Var.VarType.PinCategory.ToString());
			VarObj->SetStringField(TEXT("sub_category"), Var.VarType.PinSubCategory.ToString());
			VarObj->SetStringField(TEXT("default_value"), Var.DefaultValue);
			VarsList.Add(MakeShared<FJsonValueObject>(VarObj));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("blueprint"), Blueprint->GetName());
		Data->SetArrayField(TEXT("variables"), VarsList);
		Data->SetNumberField(TEXT("count"), VarsList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterBlueprintTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FFindBlueprintTool>());
	Registry.RegisterTool(MakeShared<FGetBlueprintInfoTool>());
	Registry.RegisterTool(MakeShared<FGetBlueprintParentClassTool>());
	Registry.RegisterTool(MakeShared<FGetBlueprintVariablesTool>());
}
