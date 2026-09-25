#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "GameFramework/Actor.h"
#include "Components/ActorComponent.h"
#include "Components/SceneComponent.h"
#include "ScopedTransaction.h"

// Helper to find an actor by name or label
static AActor* FindActorByNameOrLabel(UWorld* World, const FString& Identifier)
{
	if (!World) return nullptr;

	for (TActorIterator<AActor> It(World); It; ++It)
	{
		AActor* Actor = *It;
		if (!Actor) continue;

		if (Actor->GetName().Equals(Identifier, ESearchCase::IgnoreCase) ||
			Actor->GetActorLabel().Equals(Identifier, ESearchCase::IgnoreCase))
		{
			return Actor;
		}
	}
	return nullptr;
}

// ============================================================================
// Tool: list_level_actors
// ============================================================================
class FListLevelActorsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("list_level_actors"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Lists actors in the current level with optional filtering by class, name pattern, or tag."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		
		TSharedPtr<FJsonObject> ClassFilter = MakeShared<FJsonObject>();
		ClassFilter->SetStringField(TEXT("type"), TEXT("string"));
		ClassFilter->SetStringField(TEXT("description"), TEXT("Filter by actor class name (substring match)"));
		Props->SetObjectField(TEXT("class_filter"), ClassFilter);

		TSharedPtr<FJsonObject> NameFilter = MakeShared<FJsonObject>();
		NameFilter->SetStringField(TEXT("type"), TEXT("string"));
		NameFilter->SetStringField(TEXT("description"), TEXT("Filter by actor name or label (substring match)"));
		Props->SetObjectField(TEXT("name_filter"), NameFilter);

		TSharedPtr<FJsonObject> TagFilter = MakeShared<FJsonObject>();
		TagFilter->SetStringField(TEXT("type"), TEXT("string"));
		TagFilter->SetStringField(TEXT("description"), TEXT("Filter by actor tag"));
		Props->SetObjectField(TEXT("tag_filter"), TagFilter);

		TSharedPtr<FJsonObject> MaxResults = MakeShared<FJsonObject>();
		MaxResults->SetStringField(TEXT("type"), TEXT("number"));
		MaxResults->SetStringField(TEXT("description"), TEXT("Max results to return (default 50, max 500)"));
		Props->SetObjectField(TEXT("max_results"), MaxResults);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ClassFilter = Arguments->GetStringField(TEXT("class_filter"));
		FString NameFilter = Arguments->GetStringField(TEXT("name_filter"));
		FString TagFilter = Arguments->GetStringField(TEXT("tag_filter"));
		int32 MaxResults = Arguments->HasField(TEXT("max_results")) ? FMath::Clamp((int32)Arguments->GetNumberField(TEXT("max_results")), 1, 500) : 50;

		TArray<TSharedPtr<FJsonValue>> ActorsList;
		int32 TotalFound = 0;

		for (TActorIterator<AActor> It(World); It; ++It)
		{
			AActor* Actor = *It;
			if (!Actor) continue;

			if (!ClassFilter.IsEmpty() && !Actor->GetClass()->GetName().Contains(ClassFilter)) continue;
			if (!NameFilter.IsEmpty() && !Actor->GetName().Contains(NameFilter) && !Actor->GetActorLabel().Contains(NameFilter)) continue;
			if (!TagFilter.IsEmpty() && !Actor->Tags.Contains(*TagFilter)) continue;

			TotalFound++;

			if (ActorsList.Num() < MaxResults)
			{
				TSharedPtr<FJsonObject> ActorObj = MakeShared<FJsonObject>();
				ActorObj->SetStringField(TEXT("name"), Actor->GetName());
				ActorObj->SetStringField(TEXT("label"), Actor->GetActorLabel());
				ActorObj->SetStringField(TEXT("class"), Actor->GetClass()->GetName());
				ActorObj->SetBoolField(TEXT("is_hidden"), Actor->IsHiddenEd());
				ActorsList.Add(MakeShared<FJsonValueObject>(ActorObj));
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("actors"), ActorsList);
		Data->SetNumberField(TEXT("returned_count"), ActorsList.Num());
		Data->SetNumberField(TEXT("total_matching"), TotalFound);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: find_actor
// ============================================================================
class FFindActorTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_actor"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Finds a specific actor by name or label and returns its basic information."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of the actor to locate"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		AActor* Actor = FindActorByNameOrLabel(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), Actor->GetName());
		Data->SetStringField(TEXT("label"), Actor->GetActorLabel());
		Data->SetStringField(TEXT("class"), Actor->GetClass()->GetName());
		Data->SetStringField(TEXT("path"), Actor->GetPathName());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_actor_info
// ============================================================================
class FGetActorInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_actor_info"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Returns detailed information about an actor including tags, components, owner, and transform."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of the actor"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		AActor* Actor = FindActorByNameOrLabel(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), Actor->GetName());
		Data->SetStringField(TEXT("label"), Actor->GetActorLabel());
		Data->SetStringField(TEXT("class"), Actor->GetClass()->GetName());
		Data->SetStringField(TEXT("owner"), Actor->GetOwner() ? Actor->GetOwner()->GetName() : TEXT("None"));

		TArray<TSharedPtr<FJsonValue>> TagsArray;
		for (const FName& Tag : Actor->Tags)
		{
			TagsArray.Add(MakeShared<FJsonValueString>(Tag.ToString()));
		}
		Data->SetArrayField(TEXT("tags"), TagsArray);

		TArray<TSharedPtr<FJsonValue>> ComponentsArray;
		TInlineComponentArray<UActorComponent*> Components(Actor);
		for (UActorComponent* Comp : Components)
		{
			if (Comp)
			{
				TSharedPtr<FJsonObject> CompObj = MakeShared<FJsonObject>();
				CompObj->SetStringField(TEXT("name"), Comp->GetName());
				CompObj->SetStringField(TEXT("class"), Comp->GetClass()->GetName());
				ComponentsArray.Add(MakeShared<FJsonValueObject>(CompObj));
			}
		}
		Data->SetArrayField(TEXT("components"), ComponentsArray);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_actor_transform
// ============================================================================
class FGetActorTransformTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_actor_transform"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Gets world location, rotation, and scale of a specified actor."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of the actor"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		AActor* Actor = FindActorByNameOrLabel(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		FVector Loc = Actor->GetActorLocation();
		FRotator Rot = Actor->GetActorRotation();
		FVector Scale = Actor->GetActorScale3D();

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());

		TSharedPtr<FJsonObject> LocObj = MakeShared<FJsonObject>();
		LocObj->SetNumberField(TEXT("x"), Loc.X);
		LocObj->SetNumberField(TEXT("y"), Loc.Y);
		LocObj->SetNumberField(TEXT("z"), Loc.Z);
		Data->SetObjectField(TEXT("location"), LocObj);

		TSharedPtr<FJsonObject> RotObj = MakeShared<FJsonObject>();
		RotObj->SetNumberField(TEXT("pitch"), Rot.Pitch);
		RotObj->SetNumberField(TEXT("yaw"), Rot.Yaw);
		RotObj->SetNumberField(TEXT("roll"), Rot.Roll);
		Data->SetObjectField(TEXT("rotation"), RotObj);

		TSharedPtr<FJsonObject> ScaleObj = MakeShared<FJsonObject>();
		ScaleObj->SetNumberField(TEXT("x"), Scale.X);
		ScaleObj->SetNumberField(TEXT("y"), Scale.Y);
		ScaleObj->SetNumberField(TEXT("z"), Scale.Z);
		Data->SetObjectField(TEXT("scale"), ScaleObj);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: set_actor_transform
// ============================================================================
class FSetActorTransformTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("set_actor_transform"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Sets world location, rotation, and/or scale of an actor with Undo/Redo transaction support."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::SafeWrite; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of the actor"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		TSharedPtr<FJsonObject> LocProp = MakeShared<FJsonObject>();
		LocProp->SetStringField(TEXT("type"), TEXT("object"));
		LocProp->SetStringField(TEXT("description"), TEXT("Optional target location {x, y, z}"));
		Props->SetObjectField(TEXT("location"), LocProp);

		TSharedPtr<FJsonObject> RotProp = MakeShared<FJsonObject>();
		RotProp->SetStringField(TEXT("type"), TEXT("object"));
		RotProp->SetStringField(TEXT("description"), TEXT("Optional target rotation {pitch, yaw, roll}"));
		Props->SetObjectField(TEXT("rotation"), RotProp);

		TSharedPtr<FJsonObject> ScaleProp = MakeShared<FJsonObject>();
		ScaleProp->SetStringField(TEXT("type"), TEXT("object"));
		ScaleProp->SetStringField(TEXT("description"), TEXT("Optional target scale {x, y, z}"));
		Props->SetObjectField(TEXT("scale"), ScaleProp);

		Schema->SetObjectField(TEXT("properties"), Props);

		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		AActor* Actor = FindActorByNameOrLabel(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		// Scoped transaction for Undo/Redo (Ctrl+Z)
		const FScopedTransaction Transaction(FText::FromString(FString::Printf(TEXT("ConanMCP: Set Transform of %s"), *Actor->GetActorLabel())));
		Actor->Modify();

		if (Arguments->HasField(TEXT("location")))
		{
			const TSharedPtr<FJsonObject> LocObj = Arguments->GetObjectField(TEXT("location"));
			FVector Loc = Actor->GetActorLocation();
			if (LocObj->HasField(TEXT("x"))) Loc.X = LocObj->GetNumberField(TEXT("x"));
			if (LocObj->HasField(TEXT("y"))) Loc.Y = LocObj->GetNumberField(TEXT("y"));
			if (LocObj->HasField(TEXT("z"))) Loc.Z = LocObj->GetNumberField(TEXT("z"));
			Actor->SetActorLocation(Loc);
		}

		if (Arguments->HasField(TEXT("rotation")))
		{
			const TSharedPtr<FJsonObject> RotObj = Arguments->GetObjectField(TEXT("rotation"));
			FRotator Rot = Actor->GetActorRotation();
			if (RotObj->HasField(TEXT("pitch"))) Rot.Pitch = RotObj->GetNumberField(TEXT("pitch"));
			if (RotObj->HasField(TEXT("yaw"))) Rot.Yaw = RotObj->GetNumberField(TEXT("yaw"));
			if (RotObj->HasField(TEXT("roll"))) Rot.Roll = RotObj->GetNumberField(TEXT("roll"));
			Actor->SetActorRotation(Rot);
		}

		if (Arguments->HasField(TEXT("scale")))
		{
			const TSharedPtr<FJsonObject> ScaleObj = Arguments->GetObjectField(TEXT("scale"));
			FVector Scale = Actor->GetActorScale3D();
			if (ScaleObj->HasField(TEXT("x"))) Scale.X = ScaleObj->GetNumberField(TEXT("x"));
			if (ScaleObj->HasField(TEXT("y"))) Scale.Y = ScaleObj->GetNumberField(TEXT("y"));
			if (ScaleObj->HasField(TEXT("z"))) Scale.Z = ScaleObj->GetNumberField(TEXT("z"));
			Actor->SetActorScale3D(Scale);
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());
		Data->SetBoolField(TEXT("success"), true);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_actor_components
// ============================================================================
class FGetActorComponentsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_actor_components"); }
	virtual FString GetCategory() const override { return TEXT("Actors"); }
	virtual FString GetDescription() const override { return TEXT("Lists all components attached to an actor with their class and hierarchy info."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of the actor"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		AActor* Actor = FindActorByNameOrLabel(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		TArray<TSharedPtr<FJsonValue>> CompList;
		TInlineComponentArray<UActorComponent*> Components(Actor);

		for (UActorComponent* Comp : Components)
		{
			if (!Comp) continue;

			TSharedPtr<FJsonObject> CompObj = MakeShared<FJsonObject>();
			CompObj->SetStringField(TEXT("name"), Comp->GetName());
			CompObj->SetStringField(TEXT("class"), Comp->GetClass()->GetName());
			CompObj->SetBoolField(TEXT("is_scene_component"), Comp->IsA<USceneComponent>());

			if (USceneComponent* SceneComp = Cast<USceneComponent>(Comp))
			{
				CompObj->SetStringField(TEXT("attach_parent"), SceneComp->GetAttachParent() ? SceneComp->GetAttachParent()->GetName() : TEXT("None"));
				CompObj->SetStringField(TEXT("attach_socket"), SceneComp->GetAttachSocketName().ToString());
			}

			CompList.Add(MakeShared<FJsonValueObject>(CompObj));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());
		Data->SetArrayField(TEXT("components"), CompList);
		Data->SetNumberField(TEXT("count"), CompList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterActorTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FListLevelActorsTool>());
	Registry.RegisterTool(MakeShared<FFindActorTool>());
	Registry.RegisterTool(MakeShared<FGetActorInfoTool>());
	Registry.RegisterTool(MakeShared<FGetActorTransformTool>());
	Registry.RegisterTool(MakeShared<FSetActorTransformTool>());
	Registry.RegisterTool(MakeShared<FGetActorComponentsTool>());
}
