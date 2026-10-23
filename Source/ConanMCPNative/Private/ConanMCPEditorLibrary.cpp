#include "ConanMCPEditorLibrary.h"

#include "Dom/JsonObject.h"
#include "Dom/JsonValue.h"
#include "EdGraph/EdGraph.h"
#include "EdGraph/EdGraphNode.h"
#include "EdGraphSchema_K2.h"
#include "Editor.h"
#include "Engine/Blueprint.h"
#include "Engine/SCS_Node.h"
#include "Engine/SimpleConstructionScript.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "Kismet2/BlueprintEditorUtils.h"
#include "Kismet2/CompilerResultsLog.h"
#include "Kismet2/KismetEditorUtilities.h"
#include "Landscape.h"
#include "LandscapeEdit.h"
#include "LandscapeInfo.h"
#include "LandscapeLayerInfoObject.h"
#include "LandscapeProxy.h"
#include "Misc/Base64.h"
#include "Misc/EngineVersionComparison.h"
#include "ScopedTransaction.h"
#include "Serialization/JsonSerializer.h"
#include "Serialization/JsonWriter.h"

#define LOCTEXT_NAMESPACE "ConanMCPNative"

namespace ConanMCPNative
{
	static FString ToJson(const TSharedRef<FJsonObject>& Obj)
	{
		FString Out;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(Obj, Writer);
		return Out;
	}

	static FString ToJson(const TArray<TSharedPtr<FJsonValue>>& Arr)
	{
		FString Out;
		TSharedRef<TJsonWriter<>> Writer = TJsonWriterFactory<>::Create(&Out);
		FJsonSerializer::Serialize(Arr, Writer);
		return Out;
	}

	static FString Error(const FString& Message)
	{
		TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetBoolField(TEXT("ok"), false);
		Obj->SetStringField(TEXT("error"), Message);
		return ToJson(Obj);
	}

	static TSharedPtr<FJsonObject> Vec(const FVector& V)
	{
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetNumberField(TEXT("x"), V.X);
		Obj->SetNumberField(TEXT("y"), V.Y);
		Obj->SetNumberField(TEXT("z"), V.Z);
		return Obj;
	}

	static UWorld* EditorWorld()
	{
		return GEditor ? GEditor->GetEditorWorldContext().World() : nullptr;
	}

	/** Main ALandscape actor whose label or name matches (first one when Label is empty). */
	static ALandscape* FindLandscape(const FString& Label)
	{
		UWorld* World = EditorWorld();
		if (!World)
		{
			return nullptr;
		}
		for (TActorIterator<ALandscape> It(World); It; ++It)
		{
			ALandscape* Landscape = *It;
			if (Label.IsEmpty() || Landscape->GetActorLabel().Equals(Label, ESearchCase::IgnoreCase)
				|| Landscape->GetName().Equals(Label, ESearchCase::IgnoreCase))
			{
				return Landscape;
			}
		}
		return nullptr;
	}

	static bool ValidRegion(int32 MinX, int32 MinY, int32 MaxX, int32 MaxY, int64 MaxVerts = 4097LL * 4097LL)
	{
		return MaxX >= MinX && MaxY >= MinY && int64(MaxX - MinX + 1) * int64(MaxY - MinY + 1) <= MaxVerts;
	}

	/** Runs Fn with the landscape's active edit layer selected (UE5 edit layers), then refreshes it. */
	template <typename FnType>
	static bool WithEditLayer(ALandscape* Landscape, FString& OutError, FnType&& Fn)
	{
		if (Landscape->HasLayersContent())
		{
			FGuid LayerGuid = Landscape->GetEditingLayer();
#if UE_VERSION_OLDER_THAN(5, 5, 0)
			if (!LayerGuid.IsValid() && Landscape->GetLayerCount() > 0)
			{
				LayerGuid = Landscape->GetLayer(0)->Guid;
			}
#endif
			if (!LayerGuid.IsValid())
			{
				OutError = TEXT("This landscape uses edit layers: open Landscape mode and select the layer to edit, then retry");
				return false;
			}
			FScopedSetLandscapeEditingLayer Scope(Landscape, LayerGuid, [Landscape]()
			{
				Landscape->RequestLayersContentUpdate(ELandscapeLayerUpdateMode::Update_All);
			});
			Fn();
			return true;
		}
		Fn();
		return true;
	}

	static FString PinTypeName(const FEdGraphPinType& Pin)
	{
		FString Name = Pin.PinCategory.ToString();
		if (!Pin.PinSubCategory.IsNone())
		{
			Name += TEXT(":") + Pin.PinSubCategory.ToString();
		}
		if (Pin.PinSubCategoryObject.IsValid())
		{
			Name += TEXT("<") + Pin.PinSubCategoryObject->GetName() + TEXT(">");
		}
		if (Pin.ContainerType == EPinContainerType::Array)
		{
			Name = TEXT("Array of ") + Name;
		}
		else if (Pin.ContainerType == EPinContainerType::Set)
		{
			Name = TEXT("Set of ") + Name;
		}
		else if (Pin.ContainerType == EPinContainerType::Map)
		{
			Name = TEXT("Map of ") + Name;
		}
		return Name;
	}

	static bool MakePinType(FString Type, const FString& SubType, FEdGraphPinType& Out, FString& OutError)
	{
		Out = FEdGraphPinType();
		if (Type.StartsWith(TEXT("array:")))
		{
			Out.ContainerType = EPinContainerType::Array;
			Type = Type.RightChop(6);
		}
		Type = Type.ToLower();

		auto NeedObject = [&](UClass* Expected) -> UObject*
		{
			UObject* Obj = SubType.IsEmpty() ? nullptr : StaticLoadObject(Expected, nullptr, *SubType);
			if (!Obj && !SubType.IsEmpty() && Expected == UClass::StaticClass())
			{
				// Blueprint asset path: use its generated class
				if (UBlueprint* BP = LoadObject<UBlueprint>(nullptr, *SubType))
				{
					Obj = BP->GeneratedClass;
				}
			}
			if (!Obj)
			{
				OutError = FString::Printf(TEXT("Type '%s' needs a valid SubType (got '%s')"), *Type, *SubType);
			}
			return Obj;
		};

		if (Type == TEXT("bool")) { Out.PinCategory = UEdGraphSchema_K2::PC_Boolean; }
		else if (Type == TEXT("byte")) { Out.PinCategory = UEdGraphSchema_K2::PC_Byte; }
		else if (Type == TEXT("int")) { Out.PinCategory = UEdGraphSchema_K2::PC_Int; }
		else if (Type == TEXT("int64")) { Out.PinCategory = UEdGraphSchema_K2::PC_Int64; }
		else if (Type == TEXT("float") || Type == TEXT("double") || Type == TEXT("real"))
		{
			Out.PinCategory = UEdGraphSchema_K2::PC_Real;
			Out.PinSubCategory = Type == TEXT("float") ? UEdGraphSchema_K2::PC_Float : UEdGraphSchema_K2::PC_Double;
		}
		else if (Type == TEXT("string")) { Out.PinCategory = UEdGraphSchema_K2::PC_String; }
		else if (Type == TEXT("name")) { Out.PinCategory = UEdGraphSchema_K2::PC_Name; }
		else if (Type == TEXT("text")) { Out.PinCategory = UEdGraphSchema_K2::PC_Text; }
		else if (Type == TEXT("vector")) { Out.PinCategory = UEdGraphSchema_K2::PC_Struct; Out.PinSubCategoryObject = TBaseStructure<FVector>::Get(); }
		else if (Type == TEXT("rotator")) { Out.PinCategory = UEdGraphSchema_K2::PC_Struct; Out.PinSubCategoryObject = TBaseStructure<FRotator>::Get(); }
		else if (Type == TEXT("transform")) { Out.PinCategory = UEdGraphSchema_K2::PC_Struct; Out.PinSubCategoryObject = TBaseStructure<FTransform>::Get(); }
		else if (Type == TEXT("object") || Type == TEXT("class") || Type == TEXT("soft_object") || Type == TEXT("soft_class"))
		{
			UObject* Cls = NeedObject(UClass::StaticClass());
			if (!Cls) { return false; }
			Out.PinCategory = Type == TEXT("object") ? UEdGraphSchema_K2::PC_Object
				: Type == TEXT("class") ? UEdGraphSchema_K2::PC_Class
				: Type == TEXT("soft_object") ? UEdGraphSchema_K2::PC_SoftObject : UEdGraphSchema_K2::PC_SoftClass;
			Out.PinSubCategoryObject = Cls;
		}
		else if (Type == TEXT("struct"))
		{
			UObject* Struct = NeedObject(UScriptStruct::StaticClass());
			if (!Struct) { return false; }
			Out.PinCategory = UEdGraphSchema_K2::PC_Struct;
			Out.PinSubCategoryObject = Struct;
		}
		else
		{
			OutError = FString::Printf(TEXT("Unknown variable type '%s'"), *Type);
			return false;
		}
		return true;
	}
}

using namespace ConanMCPNative;

// ---------------------------------------------------------------------------
// Landscape
// ---------------------------------------------------------------------------

FString UConanMCPEditorLibrary::GetLandscapeInfoJson()
{
	TArray<TSharedPtr<FJsonValue>> Items;
	UWorld* World = EditorWorld();
	if (!World)
	{
		return ToJson(Items);
	}
	for (TActorIterator<ALandscape> It(World); It; ++It)
	{
		ALandscape* Landscape = *It;
		ULandscapeInfo* Info = Landscape->GetLandscapeInfo();
		TSharedPtr<FJsonObject> Obj = MakeShared<FJsonObject>();
		Obj->SetStringField(TEXT("label"), Landscape->GetActorLabel());
		Obj->SetStringField(TEXT("name"), Landscape->GetName());
		Obj->SetStringField(TEXT("class"), TEXT("Landscape"));
		Obj->SetObjectField(TEXT("origin"), Vec(Landscape->GetActorLocation()));
		Obj->SetObjectField(TEXT("scale"), Vec(Landscape->GetActorScale3D()));
		Obj->SetNumberField(TEXT("component_size_quads"), Landscape->ComponentSizeQuads);
		Obj->SetNumberField(TEXT("num_subsections"), Landscape->NumSubsections);
		Obj->SetBoolField(TEXT("edit_layers"), Landscape->HasLayersContent());
		if (UMaterialInterface* Material = Landscape->GetLandscapeMaterial())
		{
			Obj->SetStringField(TEXT("material"), Material->GetPathName());
		}
		if (Info)
		{
			int32 MinX = 0, MinY = 0, MaxX = 0, MaxY = 0;
			if (Info->GetLandscapeExtent(MinX, MinY, MaxX, MaxY))
			{
				TSharedPtr<FJsonObject> Ext = MakeShared<FJsonObject>();
				Ext->SetNumberField(TEXT("min_x"), MinX);
				Ext->SetNumberField(TEXT("min_y"), MinY);
				Ext->SetNumberField(TEXT("max_x"), MaxX);
				Ext->SetNumberField(TEXT("max_y"), MaxY);
				Obj->SetObjectField(TEXT("extent_quads"), Ext);
			}
			TArray<TSharedPtr<FJsonValue>> Layers;
			for (const FLandscapeInfoLayerSettings& Layer : Info->Layers)
			{
				Layers.Add(MakeShared<FJsonValueString>(Layer.GetLayerName().ToString()));
			}
			Obj->SetArrayField(TEXT("layers"), Layers);
			Obj->SetNumberField(TEXT("num_components"), Info->XYtoComponentMap.Num());
		}
		Items.Add(MakeShared<FJsonValueObject>(Obj));
	}
	return ToJson(Items);
}

FString UConanMCPEditorLibrary::GetHeightRegionJson(const FString& LandscapeLabel, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY)
{
	ALandscape* Landscape = FindLandscape(LandscapeLabel);
	ULandscapeInfo* Info = Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	if (!Info)
	{
		return Error(TEXT("Landscape not found"));
	}
	if (!ValidRegion(MinX, MinY, MaxX, MaxY))
	{
		return Error(TEXT("Invalid or too large region"));
	}
	const int32 Width = MaxX - MinX + 1;
	const int32 Height = MaxY - MinY + 1;
	TArray<uint16> Data;
	Data.SetNumZeroed(Width * Height);
	FLandscapeEditDataInterface Edit(Info);
	int32 X1 = MinX, Y1 = MinY, X2 = MaxX, Y2 = MaxY;
	Edit.GetHeightData(X1, Y1, X2, Y2, Data.GetData(), Width);

	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	Obj->SetNumberField(TEXT("x0"), MinX);
	Obj->SetNumberField(TEXT("y0"), MinY);
	Obj->SetNumberField(TEXT("width"), Width);
	Obj->SetNumberField(TEXT("height"), Height);
	Obj->SetStringField(TEXT("data_b64"), FBase64::Encode(reinterpret_cast<const uint8*>(Data.GetData()), Data.Num() * sizeof(uint16)));
	return ToJson(Obj);
}

FString UConanMCPEditorLibrary::SetHeightRegionJson(const FString& LandscapeLabel, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY, const FString& DataBase64)
{
	ALandscape* Landscape = FindLandscape(LandscapeLabel);
	ULandscapeInfo* Info = Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	if (!Info)
	{
		return Error(TEXT("Landscape not found"));
	}
	if (!ValidRegion(MinX, MinY, MaxX, MaxY))
	{
		return Error(TEXT("Invalid or too large region"));
	}
	TArray<uint8> Bytes;
	if (!FBase64::Decode(DataBase64, Bytes))
	{
		return Error(TEXT("Invalid base64 payload"));
	}
	const int32 Width = MaxX - MinX + 1;
	const int32 Height = MaxY - MinY + 1;
	if (Bytes.Num() != Width * Height * int32(sizeof(uint16)))
	{
		return Error(FString::Printf(TEXT("Payload has %d bytes, expected %d"), Bytes.Num(), Width * Height * int32(sizeof(uint16))));
	}

	FString LayerError;
	const FScopedTransaction Transaction(LOCTEXT("SculptLandscape", "ConanMCP: Sculpt Landscape"));
	Landscape->Modify();
	const bool bOk = WithEditLayer(Landscape, LayerError, [&]()
	{
		FLandscapeEditDataInterface Edit(Info);
		Edit.SetHeightData(MinX, MinY, MaxX, MaxY, reinterpret_cast<const uint16*>(Bytes.GetData()), Width, true);
		Edit.Flush();
	});
	if (!bOk)
	{
		return Error(LayerError);
	}
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	Obj->SetNumberField(TEXT("written_vertices"), Width * Height);
	return ToJson(Obj);
}

FString UConanMCPEditorLibrary::GetWeightRegionJson(const FString& LandscapeLabel, const FString& LayerName, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY)
{
	ALandscape* Landscape = FindLandscape(LandscapeLabel);
	ULandscapeInfo* Info = Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	if (!Info)
	{
		return Error(TEXT("Landscape not found"));
	}
	ULandscapeLayerInfoObject* LayerInfo = Info->GetLayerInfoByName(FName(*LayerName));
	if (!LayerInfo)
	{
		return Error(FString::Printf(TEXT("Layer '%s' has no layer info on this landscape"), *LayerName));
	}
	if (!ValidRegion(MinX, MinY, MaxX, MaxY))
	{
		return Error(TEXT("Invalid or too large region"));
	}
	const int32 Width = MaxX - MinX + 1;
	const int32 Height = MaxY - MinY + 1;
	TArray<uint8> Data;
	Data.SetNumZeroed(Width * Height);
	FLandscapeEditDataInterface Edit(Info);
	int32 X1 = MinX, Y1 = MinY, X2 = MaxX, Y2 = MaxY;
	Edit.GetWeightData(LayerInfo, X1, Y1, X2, Y2, Data.GetData(), Width);

	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	Obj->SetNumberField(TEXT("x0"), MinX);
	Obj->SetNumberField(TEXT("y0"), MinY);
	Obj->SetNumberField(TEXT("width"), Width);
	Obj->SetNumberField(TEXT("height"), Height);
	Obj->SetStringField(TEXT("data_b64"), FBase64::Encode(Data));
	return ToJson(Obj);
}

FString UConanMCPEditorLibrary::SetWeightRegionJson(const FString& LandscapeLabel, const FString& LayerName, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY, const FString& DataBase64)
{
	ALandscape* Landscape = FindLandscape(LandscapeLabel);
	ULandscapeInfo* Info = Landscape ? Landscape->GetLandscapeInfo() : nullptr;
	if (!Info)
	{
		return Error(TEXT("Landscape not found"));
	}
	ULandscapeLayerInfoObject* LayerInfo = Info->GetLayerInfoByName(FName(*LayerName));
	if (!LayerInfo)
	{
		return Error(FString::Printf(TEXT("Layer '%s' has no layer info on this landscape"), *LayerName));
	}
	TArray<uint8> Bytes;
	if (!FBase64::Decode(DataBase64, Bytes) || !ValidRegion(MinX, MinY, MaxX, MaxY)
		|| Bytes.Num() != (MaxX - MinX + 1) * (MaxY - MinY + 1))
	{
		return Error(TEXT("Invalid payload or region"));
	}
	FString LayerError;
	const FScopedTransaction Transaction(LOCTEXT("PaintLandscape", "ConanMCP: Paint Landscape Layer"));
	Landscape->Modify();
	const bool bOk = WithEditLayer(Landscape, LayerError, [&]()
	{
		FLandscapeEditDataInterface Edit(Info);
		Edit.SetAlphaData(LayerInfo, MinX, MinY, MaxX, MaxY, Bytes.GetData(), MaxX - MinX + 1);
		Edit.Flush();
	});
	if (!bOk)
	{
		return Error(LayerError);
	}
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	return ToJson(Obj);
}

// ---------------------------------------------------------------------------
// Level / editor
// ---------------------------------------------------------------------------

FString UConanMCPEditorLibrary::TraceGroundJson(float X, float Y, float StartZ, float EndZ)
{
	UWorld* World = EditorWorld();
	if (!World)
	{
		return FString();
	}
	FHitResult Hit;
	FCollisionQueryParams Params(SCENE_QUERY_STAT(ConanMCPTraceGround), true);
	if (!World->LineTraceSingleByChannel(Hit, FVector(X, Y, StartZ), FVector(X, Y, EndZ), ECC_Visibility, Params))
	{
		return FString();
	}
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetObjectField(TEXT("location"), Vec(Hit.ImpactPoint));
	Obj->SetObjectField(TEXT("normal"), Vec(Hit.ImpactNormal));
	Obj->SetNumberField(TEXT("slope_deg"), FMath::RadiansToDegrees(FMath::Acos(FMath::Clamp(FMath::Abs(Hit.ImpactNormal.Z), 0.0, 1.0))));
	if (AActor* Actor = Hit.GetActor())
	{
		Obj->SetStringField(TEXT("actor_label"), Actor->GetActorLabel());
		Obj->SetStringField(TEXT("actor_class"), Actor->GetClass()->GetName());
	}
	return ToJson(Obj);
}

bool UConanMCPEditorLibrary::UndoLastTransaction()
{
	return GEditor ? GEditor->UndoTransaction() : false;
}

bool UConanMCPEditorLibrary::RedoLastTransaction()
{
	return GEditor ? GEditor->RedoTransaction() : false;
}

// ---------------------------------------------------------------------------
// Blueprints
// ---------------------------------------------------------------------------

FString UConanMCPEditorLibrary::CompileBlueprintJson(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return Error(TEXT("Blueprint is null"));
	}
	FCompilerResultsLog Results;
	Results.SetSourcePath(Blueprint->GetPathName());
	Results.bSilentMode = true;
	FKismetEditorUtilities::CompileBlueprint(Blueprint, EBlueprintCompileOptions::None, &Results);

	TArray<TSharedPtr<FJsonValue>> Errors, Warnings, Notes;
	for (const TSharedRef<FTokenizedMessage>& Message : Results.Messages)
	{
		const FString Text = Message->ToText().ToString();
		switch (Message->GetSeverity())
		{
		case EMessageSeverity::Error: Errors.Add(MakeShared<FJsonValueString>(Text)); break;
		case EMessageSeverity::Warning:
		case EMessageSeverity::PerformanceWarning: Warnings.Add(MakeShared<FJsonValueString>(Text)); break;
		default: Notes.Add(MakeShared<FJsonValueString>(Text)); break;
		}
	}
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), Results.NumErrors == 0);
	Obj->SetBoolField(TEXT("compiled"), true);
	Obj->SetBoolField(TEXT("has_errors"), Results.NumErrors > 0);
	Obj->SetNumberField(TEXT("num_errors"), Results.NumErrors);
	Obj->SetNumberField(TEXT("num_warnings"), Results.NumWarnings);
	Obj->SetStringField(TEXT("status"), Blueprint->Status == BS_Error ? TEXT("error")
		: Blueprint->Status == BS_UpToDateWithWarnings ? TEXT("up_to_date_with_warnings")
		: Blueprint->Status == BS_UpToDate ? TEXT("up_to_date") : TEXT("dirty"));
	Obj->SetArrayField(TEXT("errors"), Errors);
	Obj->SetArrayField(TEXT("warnings"), Warnings);
	Obj->SetArrayField(TEXT("notes"), Notes);
	Obj->SetStringField(TEXT("backend"), TEXT("native"));
	return ToJson(Obj);
}

FString UConanMCPEditorLibrary::GetBlueprintDetailsJson(UBlueprint* Blueprint)
{
	if (!Blueprint)
	{
		return Error(TEXT("Blueprint is null"));
	}
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	Obj->SetStringField(TEXT("name"), Blueprint->GetName());
	Obj->SetStringField(TEXT("path"), Blueprint->GetPathName());
	Obj->SetStringField(TEXT("parent_class"), Blueprint->ParentClass ? Blueprint->ParentClass->GetName() : TEXT("None"));
	Obj->SetStringField(TEXT("parent_class_path"), Blueprint->ParentClass ? Blueprint->ParentClass->GetPathName() : TEXT(""));
	Obj->SetStringField(TEXT("backend"), TEXT("native"));

	UObject* CDO = Blueprint->GeneratedClass ? Blueprint->GeneratedClass->GetDefaultObject() : nullptr;
	TArray<TSharedPtr<FJsonValue>> Vars;
	for (const FBPVariableDescription& Var : Blueprint->NewVariables)
	{
		TSharedPtr<FJsonObject> V = MakeShared<FJsonObject>();
		V->SetStringField(TEXT("name"), Var.VarName.ToString());
		V->SetStringField(TEXT("type"), PinTypeName(Var.VarType));
		V->SetStringField(TEXT("category"), Var.Category.ToString());
		V->SetStringField(TEXT("default_value"), Var.DefaultValue);
		V->SetBoolField(TEXT("instance_editable"), (Var.PropertyFlags & CPF_DisableEditOnInstance) == 0);
		V->SetBoolField(TEXT("replicated"), (Var.PropertyFlags & CPF_Net) != 0);
		if (CDO)
		{
			if (FProperty* Prop = CDO->GetClass()->FindPropertyByName(Var.VarName))
			{
				FString Exported;
				Prop->ExportTextItem_Direct(Exported, Prop->ContainerPtrToValuePtr<void>(CDO), nullptr, CDO, PPF_None);
				V->SetStringField(TEXT("value"), Exported);
			}
		}
		Vars.Add(MakeShared<FJsonValueObject>(V));
	}
	Obj->SetArrayField(TEXT("variables"), Vars);

	TArray<TSharedPtr<FJsonValue>> Components;
	if (Blueprint->SimpleConstructionScript)
	{
		for (USCS_Node* Node : Blueprint->SimpleConstructionScript->GetAllNodes())
		{
			if (!Node)
			{
				continue;
			}
			TSharedPtr<FJsonObject> C = MakeShared<FJsonObject>();
			C->SetStringField(TEXT("name"), Node->GetVariableName().ToString());
			C->SetStringField(TEXT("class"), Node->ComponentClass ? Node->ComponentClass->GetName() : TEXT("None"));
			C->SetStringField(TEXT("parent"), Node->ParentComponentOrVariableName.ToString());
			Components.Add(MakeShared<FJsonValueObject>(C));
		}
	}
	Obj->SetArrayField(TEXT("components"), Components);

	auto DescribeGraphs = [](const TArray<TObjectPtr<UEdGraph>>& Graphs)
	{
		TArray<TSharedPtr<FJsonValue>> Out;
		for (UEdGraph* Graph : Graphs)
		{
			if (!Graph)
			{
				continue;
			}
			TSharedPtr<FJsonObject> G = MakeShared<FJsonObject>();
			G->SetStringField(TEXT("name"), Graph->GetName());
			G->SetNumberField(TEXT("node_count"), Graph->Nodes.Num());
			TArray<TSharedPtr<FJsonValue>> Nodes;
			for (UEdGraphNode* Node : Graph->Nodes)
			{
				if (Node && Nodes.Num() < 200)
				{
					Nodes.Add(MakeShared<FJsonValueString>(Node->GetNodeTitle(ENodeTitleType::ListView).ToString()));
				}
			}
			G->SetArrayField(TEXT("nodes"), Nodes);
			Out.Add(MakeShared<FJsonValueObject>(G));
		}
		return Out;
	};
	TSharedPtr<FJsonObject> GraphsObj = MakeShared<FJsonObject>();
	GraphsObj->SetArrayField(TEXT("event_graphs"), DescribeGraphs(Blueprint->UbergraphPages));
	GraphsObj->SetArrayField(TEXT("functions"), DescribeGraphs(Blueprint->FunctionGraphs));
	GraphsObj->SetArrayField(TEXT("macros"), DescribeGraphs(Blueprint->MacroGraphs));
	Obj->SetObjectField(TEXT("graphs"), GraphsObj);

	TArray<TSharedPtr<FJsonValue>> Interfaces;
	for (const FBPInterfaceDescription& Interface : Blueprint->ImplementedInterfaces)
	{
		if (Interface.Interface)
		{
			Interfaces.Add(MakeShared<FJsonValueString>(Interface.Interface->GetName()));
		}
	}
	Obj->SetArrayField(TEXT("interfaces"), Interfaces);
	return ToJson(Obj);
}

FString UConanMCPEditorLibrary::AddBlueprintVariableJson(UBlueprint* Blueprint, const FString& Name, const FString& Type, const FString& SubType,
	const FString& DefaultValue, const FString& Category)
{
	if (!Blueprint)
	{
		return Error(TEXT("Blueprint is null"));
	}
	const FName VarName(*Name);
	if (FBlueprintEditorUtils::FindNewVariableIndex(Blueprint, VarName) != INDEX_NONE)
	{
		return Error(FString::Printf(TEXT("Variable '%s' already exists"), *Name));
	}
	FEdGraphPinType PinType;
	FString TypeError;
	if (!MakePinType(Type, SubType, PinType, TypeError))
	{
		return Error(TypeError);
	}
	const FScopedTransaction Transaction(LOCTEXT("AddVariable", "ConanMCP: Add Blueprint Variable"));
	Blueprint->Modify();
	if (!FBlueprintEditorUtils::AddMemberVariable(Blueprint, VarName, PinType, DefaultValue))
	{
		return Error(TEXT("AddMemberVariable failed"));
	}
	if (!Category.IsEmpty())
	{
		FBlueprintEditorUtils::SetBlueprintVariableCategory(Blueprint, VarName, nullptr, FText::FromString(Category));
	}
	FBlueprintEditorUtils::MarkBlueprintAsStructurallyModified(Blueprint);
	TSharedRef<FJsonObject> Obj = MakeShared<FJsonObject>();
	Obj->SetBoolField(TEXT("ok"), true);
	Obj->SetStringField(TEXT("type"), PinTypeName(PinType));
	return ToJson(Obj);
}

#undef LOCTEXT_NAMESPACE
