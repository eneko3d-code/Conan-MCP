#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Engine/DataTable.h"
#include "JsonObjectConverter.h"

// ============================================================================
// Tool: find_datatable
// ============================================================================
class FFindDataTableTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_datatable"); }
	virtual FString GetCategory() const override { return TEXT("DataTable"); }
	virtual FString GetDescription() const override { return TEXT("Searches for DataTable assets matching a name or path filter."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> NameProp = MakeShared<FJsonObject>();
		NameProp->SetStringField(TEXT("type"), TEXT("string"));
		NameProp->SetStringField(TEXT("description"), TEXT("DataTable name or substring (e.g. 'ItemTable')"));
		Props->SetObjectField(TEXT("name"), NameProp);

		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Package path prefix"));
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
		Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("DataTable")));

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
		Data->SetArrayField(TEXT("datatables"), Results);
		Data->SetNumberField(TEXT("count"), Results.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_datatable_info
// ============================================================================
class FGetDataTableInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_datatable_info"); }
	virtual FString GetCategory() const override { return TEXT("DataTable"); }
	virtual FString GetDescription() const override { return TEXT("Returns row struct type, row count, and row names of a DataTable."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("DataTable asset path (e.g. '/Game/Data/ItemTable')"));
		Props->SetObjectField(TEXT("datatable_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("datatable_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString TablePath = Arguments->GetStringField(TEXT("datatable_path"));
		UDataTable* Table = LoadObject<UDataTable>(nullptr, *TablePath);
		if (!Table)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load DataTable at '%s'"), *TablePath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), Table->GetName());
		Data->SetStringField(TEXT("row_struct"), Table->RowStruct ? Table->RowStruct->GetName() : TEXT("None"));
		Data->SetNumberField(TEXT("row_count"), Table->GetRowMap().Num());

		TArray<TSharedPtr<FJsonValue>> RowNames;
		for (const auto& Pair : Table->GetRowMap())
		{
			RowNames.Add(MakeShared<FJsonValueString>(Pair.Key.ToString()));
			if (RowNames.Num() >= 100) break; // Limit initial preview list
		}
		Data->SetArrayField(TEXT("preview_row_names"), RowNames);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: list_datatable_rows
// ============================================================================
class FListDataTableRowsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("list_datatable_rows"); }
	virtual FString GetCategory() const override { return TEXT("DataTable"); }
	virtual FString GetDescription() const override { return TEXT("Lists all row names in a DataTable with pagination."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("DataTable asset path"));
		Props->SetObjectField(TEXT("datatable_path"), PathProp);

		TSharedPtr<FJsonObject> OffsetProp = MakeShared<FJsonObject>();
		OffsetProp->SetStringField(TEXT("type"), TEXT("number"));
		OffsetProp->SetStringField(TEXT("description"), TEXT("Row offset for pagination (default 0)"));
		Props->SetObjectField(TEXT("offset"), OffsetProp);

		TSharedPtr<FJsonObject> LimitProp = MakeShared<FJsonObject>();
		LimitProp->SetStringField(TEXT("type"), TEXT("number"));
		LimitProp->SetStringField(TEXT("description"), TEXT("Number of rows to return (default 50, max 200)"));
		Props->SetObjectField(TEXT("limit"), LimitProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("datatable_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString TablePath = Arguments->GetStringField(TEXT("datatable_path"));
		UDataTable* Table = LoadObject<UDataTable>(nullptr, *TablePath);
		if (!Table)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load DataTable at '%s'"), *TablePath));
		}

		int32 Offset = Arguments->HasField(TEXT("offset")) ? FMath::Max(0, (int32)Arguments->GetNumberField(TEXT("offset"))) : 0;
		int32 Limit = Arguments->HasField(TEXT("limit")) ? FMath::Clamp((int32)Arguments->GetNumberField(TEXT("limit")), 1, 200) : 50;

		TArray<FName> AllRowNames = Table->GetRowNames();
		TArray<TSharedPtr<FJsonValue>> PagedRowNames;

		for (int32 i = Offset; i < AllRowNames.Num() && PagedRowNames.Num() < Limit; i++)
		{
			PagedRowNames.Add(MakeShared<FJsonValueString>(AllRowNames[i].ToString()));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("datatable"), Table->GetName());
		Data->SetNumberField(TEXT("total_rows"), AllRowNames.Num());
		Data->SetNumberField(TEXT("offset"), Offset);
		Data->SetNumberField(TEXT("limit"), Limit);
		Data->SetArrayField(TEXT("rows"), PagedRowNames);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_datatable_row
// ============================================================================
class FGetDataTableRowTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_datatable_row"); }
	virtual FString GetCategory() const override { return TEXT("DataTable"); }
	virtual FString GetDescription() const override { return TEXT("Returns the struct data of a specific row in a DataTable as JSON."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("DataTable asset path"));
		Props->SetObjectField(TEXT("datatable_path"), PathProp);

		TSharedPtr<FJsonObject> RowProp = MakeShared<FJsonObject>();
		RowProp->SetStringField(TEXT("type"), TEXT("string"));
		RowProp->SetStringField(TEXT("description"), TEXT("Row name to fetch"));
		Props->SetObjectField(TEXT("row_name"), RowProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("datatable_path")));
		Req.Add(MakeShared<FJsonValueString>(TEXT("row_name")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString TablePath = Arguments->GetStringField(TEXT("datatable_path"));
		FString RowNameStr = Arguments->GetStringField(TEXT("row_name"));

		UDataTable* Table = LoadObject<UDataTable>(nullptr, *TablePath);
		if (!Table)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load DataTable at '%s'"), *TablePath));
		}

		uint8* RowData = Table->FindRowUnchecked(*RowNameStr);
		if (!RowData || !Table->RowStruct)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Row '%s' not found in DataTable '%s'"), *RowNameStr, *TablePath));
		}

		TSharedPtr<FJsonObject> RowJsonObj = MakeShared<FJsonObject>();
		if (!FJsonObjectConverter::UStructToJsonObject(Table->RowStruct, RowData, RowJsonObj.ToSharedRef(), 0, 0))
		{
			return FConanMCPToolResult::Error(TEXT("Failed to serialize row struct to JSON"));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("datatable"), Table->GetName());
		Data->SetStringField(TEXT("row_name"), RowNameStr);
		Data->SetObjectField(TEXT("row_data"), RowJsonObj);

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterDataTableTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FFindDataTableTool>());
	Registry.RegisterTool(MakeShared<FGetDataTableInfoTool>());
	Registry.RegisterTool(MakeShared<FListDataTableRowsTool>());
	Registry.RegisterTool(MakeShared<FGetDataTableRowTool>());
}
