#pragma once

#include "CoreMinimal.h"
#include "Kismet/BlueprintFunctionLibrary.h"
#include "ConanMCPEditorLibrary.generated.h"

class UBlueprint;

/**
 * Editor helpers exposed to Python as unreal.ConanMCPEditorLibrary.
 *
 * Every function returns a JSON string ({"ok": true, ...} or {"ok": false, "error": "..."})
 * so the Python side does not depend on how a given engine version marshals out-params.
 * Landscape coordinates are landscape-space vertex indices (inclusive bounds).
 */
UCLASS()
class CONANMCPNATIVE_API UConanMCPEditorLibrary : public UBlueprintFunctionLibrary
{
	GENERATED_BODY()

public:
	/** JSON array describing every landscape in the editor world. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Landscape")
	static FString GetLandscapeInfoJson();

	/** Reads heights (uint16, little-endian, base64) of an inclusive vertex region. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Landscape")
	static FString GetHeightRegionJson(const FString& LandscapeLabel, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY);

	/** Writes heights of an inclusive vertex region inside an undoable transaction. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Landscape")
	static FString SetHeightRegionJson(const FString& LandscapeLabel, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY, const FString& DataBase64);

	/** Reads paint weights (uint8, base64) of a landscape layer. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Landscape")
	static FString GetWeightRegionJson(const FString& LandscapeLabel, const FString& LayerName, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY);

	/** Writes paint weights of a landscape layer inside an undoable transaction. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Landscape")
	static FString SetWeightRegionJson(const FString& LandscapeLabel, const FString& LayerName, int32 MinX, int32 MinY, int32 MaxX, int32 MaxY, const FString& DataBase64);

	/** Vertical visibility trace; empty string when nothing is hit. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Level")
	static FString TraceGroundJson(float X, float Y, float StartZ, float EndZ);

	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Editor")
	static bool UndoLastTransaction();

	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Editor")
	static bool RedoLastTransaction();

	/** Compiles a Blueprint and returns status plus every compiler message. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Blueprint")
	static FString CompileBlueprintJson(UBlueprint* Blueprint);

	/** Variables (exact pin types), components (SCS tree), graphs with node titles, interfaces. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Blueprint")
	static FString GetBlueprintDetailsJson(UBlueprint* Blueprint);

	/** Adds a member variable. Type: bool, byte, int, int64, float, double, string, name, text, vector, rotator,
	 *  transform, object, class, soft_object, soft_class, struct (the last five need SubType = class/struct path).
	 *  Prefix the type with "array:" for an array. */
	UFUNCTION(BlueprintCallable, Category = "ConanMCP|Blueprint")
	static FString AddBlueprintVariableJson(UBlueprint* Blueprint, const FString& Name, const FString& Type, const FString& SubType,
		const FString& DefaultValue, const FString& Category);
};
