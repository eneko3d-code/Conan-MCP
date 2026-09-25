#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "Editor.h"
#include "Engine/World.h"
#include "Engine/Selection.h"
#include "GameFramework/Actor.h"
#include "FileHelpers.h"

// ============================================================================
// Tool: get_editor_status
// ============================================================================
class FGetEditorStatusTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_editor_status"); }
	virtual FString GetCategory() const override { return TEXT("Editor"); }
	virtual FString GetDescription() const override { return TEXT("Returns editor status including engine version, active level name, world type, and play mode."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));
		Schema->SetObjectField(TEXT("properties"), MakeShared<FJsonObject>());
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("engine_version"), TEXT("5.8.2-377096+++exiles+release"));
		Data->SetStringField(TEXT("devkit"), TEXT("Conan Exiles Enhanced DevKit"));

		if (GEditor)
		{
			UWorld* World = GEditor->GetEditorWorldContext().World();
			if (World)
			{
				Data->SetStringField(TEXT("current_world"), World->GetName());
				Data->SetStringField(TEXT("current_map_path"), World->GetPathName());
				Data->SetBoolField(TEXT("is_play_in_editor"), GEditor->PlayWorld != nullptr);
			}
			else
			{
				Data->SetStringField(TEXT("current_world"), TEXT("None"));
			}
			Data->SetBoolField(TEXT("is_editor_active"), true);
		}
		else
		{
			Data->SetBoolField(TEXT("is_editor_active"), false);
		}

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_current_level
// ============================================================================
class FGetCurrentLevelTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_current_level"); }
	virtual FString GetCategory() const override { return TEXT("Editor"); }
	virtual FString GetDescription() const override { return TEXT("Returns details of the currently loaded level (path, actor count, dirty status)."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));
		Schema->SetObjectField(TEXT("properties"), MakeShared<FJsonObject>());
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor)
		{
			return FConanMCPToolResult::Error(TEXT("Editor is not initialized"));
		}

		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World)
		{
			return FConanMCPToolResult::Error(TEXT("No active world loaded in editor"));
		}

		ULevel* CurrentLevel = World->GetCurrentLevel();
		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("level_name"), World->GetName());
		Data->SetStringField(TEXT("package_name"), World->GetOutermost()->GetName());
		Data->SetBoolField(TEXT("is_dirty"), World->GetOutermost()->IsDirty());
		Data->SetNumberField(TEXT("actor_count"), CurrentLevel ? CurrentLevel->Actors.Num() : 0);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: save_current_level
// ============================================================================
class FSaveCurrentLevelTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("save_current_level"); }
	virtual FString GetCategory() const override { return TEXT("Editor"); }
	virtual FString GetDescription() const override { return TEXT("Saves the currently active level in the editor."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::SafeWrite; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));
		Schema->SetObjectField(TEXT("properties"), MakeShared<FJsonObject>());
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor)
		{
			return FConanMCPToolResult::Error(TEXT("Editor is not initialized"));
		}

		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World)
		{
			return FConanMCPToolResult::Error(TEXT("No active world loaded in editor"));
		}

		bool bSaved = FEditorFileUtils::SaveCurrentLevel();
		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetBoolField(TEXT("saved"), bSaved);
		Data->SetStringField(TEXT("level_name"), World->GetName());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_selected_actors
// ============================================================================
class FGetSelectedActorsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_selected_actors"); }
	virtual FString GetCategory() const override { return TEXT("Editor"); }
	virtual FString GetDescription() const override { return TEXT("Returns all currently selected actors in the viewport with their labels, classes, and transforms."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));
		Schema->SetObjectField(TEXT("properties"), MakeShared<FJsonObject>());
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor)
		{
			return FConanMCPToolResult::Error(TEXT("Editor is not initialized"));
		}

		USelection* SelectedActors = GEditor->GetSelectedActors();
		TArray<TSharedPtr<FJsonValue>> ActorsList;

		if (SelectedActors)
		{
			for (FSelectionIterator It(*SelectedActors); It; ++It)
			{
				AActor* Actor = Cast<AActor>(*It);
				if (!Actor) continue;

				TSharedPtr<FJsonObject> ActorObj = MakeShared<FJsonObject>();
				ActorObj->SetStringField(TEXT("name"), Actor->GetName());
				ActorObj->SetStringField(TEXT("label"), Actor->GetActorLabel());
				ActorObj->SetStringField(TEXT("class"), Actor->GetClass()->GetName());

				FVector Loc = Actor->GetActorLocation();
				FRotator Rot = Actor->GetActorRotation();
				FVector Scale = Actor->GetActorScale3D();

				TSharedPtr<FJsonObject> LocObj = MakeShared<FJsonObject>();
				LocObj->SetNumberField(TEXT("x"), Loc.X);
				LocObj->SetNumberField(TEXT("y"), Loc.Y);
				LocObj->SetNumberField(TEXT("z"), Loc.Z);
				ActorObj->SetObjectField(TEXT("location"), LocObj);

				TSharedPtr<FJsonObject> RotObj = MakeShared<FJsonObject>();
				RotObj->SetNumberField(TEXT("pitch"), Rot.Pitch);
				RotObj->SetNumberField(TEXT("yaw"), Rot.Yaw);
				RotObj->SetNumberField(TEXT("roll"), Rot.Roll);
				ActorObj->SetObjectField(TEXT("rotation"), RotObj);

				TSharedPtr<FJsonObject> ScaleObj = MakeShared<FJsonObject>();
				ScaleObj->SetNumberField(TEXT("x"), Scale.X);
				ScaleObj->SetNumberField(TEXT("y"), Scale.Y);
				ScaleObj->SetNumberField(TEXT("z"), Scale.Z);
				ActorObj->SetObjectField(TEXT("scale"), ScaleObj);

				ActorsList.Add(MakeShared<FJsonValueObject>(ActorObj));
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("selected_actors"), ActorsList);
		Data->SetNumberField(TEXT("count"), ActorsList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterEditorTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FGetEditorStatusTool>());
	Registry.RegisterTool(MakeShared<FGetCurrentLevelTool>());
	Registry.RegisterTool(MakeShared<FSaveCurrentLevelTool>());
	Registry.RegisterTool(MakeShared<FGetSelectedActorsTool>());
}
