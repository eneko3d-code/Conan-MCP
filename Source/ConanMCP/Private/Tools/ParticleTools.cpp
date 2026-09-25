#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "Editor.h"
#include "Engine/World.h"
#include "EngineUtils.h"
#include "AssetRegistry/AssetRegistryModule.h"
#include "AssetRegistry/IAssetRegistry.h"
#include "Particles/ParticleSystem.h"
#include "Particles/ParticleSystemComponent.h"
#include "NiagaraSystem.h"
#include "NiagaraComponent.h"
#include "NiagaraFunctionLibrary.h"
#include "Components/SkeletalMeshComponent.h"
#include "ScopedTransaction.h"

// Name tag for preview particles created by ConanMCP
static const FName CONAN_MCP_PREVIEW_TAG = FName(TEXT("ConanMCP_PreviewParticle"));

// Helper to find an actor by name or label
static AActor* FindActorHelper(UWorld* World, const FString& Identifier)
{
	if (!World) return nullptr;
	for (TActorIterator<AActor> It(World); It; ++It)
	{
		AActor* Actor = *It;
		if (Actor && (Actor->GetName().Equals(Identifier, ESearchCase::IgnoreCase) ||
					  Actor->GetActorLabel().Equals(Identifier, ESearchCase::IgnoreCase)))
		{
			return Actor;
		}
	}
	return nullptr;
}

// ============================================================================
// Tool: find_particle_systems
// ============================================================================
class FFindParticleSystemsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("find_particle_systems"); }
	virtual FString GetCategory() const override { return TEXT("Particles"); }
	virtual FString GetDescription() const override { return TEXT("Searches for both Niagara systems and Cascade particle systems in the project."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

		TSharedPtr<FJsonObject> NameProp = MakeShared<FJsonObject>();
		NameProp->SetStringField(TEXT("type"), TEXT("string"));
		NameProp->SetStringField(TEXT("description"), TEXT("Substring match for particle system name (e.g. 'fire', 'blood', 'magic')"));
		Props->SetObjectField(TEXT("name"), NameProp);

		TSharedPtr<FJsonObject> TypeProp = MakeShared<FJsonObject>();
		TypeProp->SetStringField(TEXT("type"), TEXT("string"));
		TypeProp->SetStringField(TEXT("description"), TEXT("Filter by type: 'All', 'Niagara', or 'Cascade' (default 'All')"));
		Props->SetObjectField(TEXT("type"), TypeProp);

		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Package path prefix filter (e.g. '/Game/VFX/')"));
		Props->SetObjectField(TEXT("path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		IAssetRegistry& AssetRegistry = FModuleManager::LoadModuleChecked<FAssetRegistryModule>("AssetRegistry").Get();

		FString NameQuery = Arguments->GetStringField(TEXT("name"));
		FString TypeFilter = Arguments->HasField(TEXT("type")) ? Arguments->GetStringField(TEXT("type")) : TEXT("All");
		FString PathFilter = Arguments->GetStringField(TEXT("path"));

		TArray<FAssetData> AllAssets;
		FARFilter Filter;
		Filter.bRecursivePaths = true;
		Filter.bRecursiveClasses = true;

		if (!PathFilter.IsEmpty())
		{
			Filter.PackagePaths.Add(*PathFilter);
		}

		if (TypeFilter.Equals(TEXT("Cascade"), ESearchCase::IgnoreCase))
		{
			Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("ParticleSystem")));
		}
		else if (TypeFilter.Equals(TEXT("Niagara"), ESearchCase::IgnoreCase))
		{
			Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Niagara"), TEXT("NiagaraSystem")));
		}
		else
		{
			Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Engine"), TEXT("ParticleSystem")));
			Filter.ClassPaths.Add(FTopLevelAssetPath(TEXT("/Script/Niagara"), TEXT("NiagaraSystem")));
		}

		AssetRegistry.GetAssets(Filter, AllAssets);

		TArray<TSharedPtr<FJsonValue>> Results;
		for (const FAssetData& AssetData : AllAssets)
		{
			if (!NameQuery.IsEmpty() && !AssetData.AssetName.ToString().Contains(NameQuery))
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

// ============================================================================
// Tool: get_particle_info
// ============================================================================
class FGetParticleInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_particle_info"); }
	virtual FString GetCategory() const override { return TEXT("Particles"); }
	virtual FString GetDescription() const override { return TEXT("Returns detailed information about a Niagara or Cascade particle system asset."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Asset path of the particle system"));
		Props->SetObjectField(TEXT("particle_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("particle_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString ParticlePath = Arguments->GetStringField(TEXT("particle_path"));
		UObject* Asset = LoadObject<UObject>(nullptr, *ParticlePath);

		if (!Asset)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load particle asset at '%s'"), *ParticlePath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("name"), Asset->GetName());

		if (UNiagaraSystem* NiagaraSys = Cast<UNiagaraSystem>(Asset))
		{
			Data->SetStringField(TEXT("type"), TEXT("Niagara"));
			Data->SetBoolField(TEXT("is_valid"), NiagaraSys->IsValid());
			Data->SetNumberField(TEXT("emitter_count"), NiagaraSys->GetNumEmitters());
		}
		else if (UParticleSystem* CascadeSys = Cast<UParticleSystem>(Asset))
		{
			Data->SetStringField(TEXT("type"), TEXT("Cascade"));
			Data->SetNumberField(TEXT("emitter_count"), CascadeSys->Emitters.Num());
			Data->SetNumberField(TEXT("warmup_time"), CascadeSys->WarmupTime);
		}
		else
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Asset '%s' is not a recognized particle system"), *ParticlePath));
		}

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_character_sockets
// ============================================================================
class FGetCharacterSocketsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_character_sockets"); }
	virtual FString GetCategory() const override { return TEXT("Particles"); }
	virtual FString GetDescription() const override { return TEXT("Retrieves all attachment sockets from an actor's Skeletal Mesh Component (useful for attaching weapon/body VFX)."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of character/actor"));
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
		AActor* Actor = FindActorHelper(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		USkeletalMeshComponent* SkelMeshComp = Actor->FindComponentByClass<USkeletalMeshComponent>();
		if (!SkelMeshComp)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' does not have a SkeletalMeshComponent"), *ActorIdentifier));
		}

		TArray<TSharedPtr<FJsonValue>> SocketsList;
		TArray<FComponentSocketDescription> Sockets;
		SkelMeshComp->QuerySupportedSockets(Sockets);

		for (const FComponentSocketDescription& Sock : Sockets)
		{
			TSharedPtr<FJsonObject> SockObj = MakeShared<FJsonObject>();
			SockObj->SetStringField(TEXT("name"), Sock.Name.ToString());
			SockObj->SetStringField(TEXT("type"), Sock.Type == EComponentSocketType::Socket ? TEXT("Socket") : TEXT("Bone"));
			SocketsList.Add(MakeShared<FJsonValueObject>(SockObj));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());
		Data->SetStringField(TEXT("skeletal_mesh"), SkelMeshComp->GetSkeletalMeshAsset() ? SkelMeshComp->GetSkeletalMeshAsset()->GetName() : TEXT("None"));
		Data->SetArrayField(TEXT("sockets"), SocketsList);
		Data->SetNumberField(TEXT("count"), SocketsList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: preview_particle_on_actor
// ============================================================================
class FPreviewParticleOnActorTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("preview_particle_on_actor"); }
	virtual FString GetCategory() const override { return TEXT("Particles"); }
	virtual FString GetDescription() const override { return TEXT("Spawns a preview particle system (Niagara or Cascade) attached to an actor or specific socket."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::SafeWrite; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();

		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of target actor"));
		Props->SetObjectField(TEXT("actor"), ActorProp);

		TSharedPtr<FJsonObject> ParticleProp = MakeShared<FJsonObject>();
		ParticleProp->SetStringField(TEXT("type"), TEXT("string"));
		ParticleProp->SetStringField(TEXT("description"), TEXT("Asset path of particle system (Niagara or Cascade)"));
		Props->SetObjectField(TEXT("particle_path"), ParticleProp);

		TSharedPtr<FJsonObject> SocketProp = MakeShared<FJsonObject>();
		SocketProp->SetStringField(TEXT("type"), TEXT("string"));
		SocketProp->SetStringField(TEXT("description"), TEXT("Optional socket name to attach to (e.g. 'hand_r', 'head', 'weapon_r')"));
		Props->SetObjectField(TEXT("socket_name"), SocketProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("actor")));
		Req.Add(MakeShared<FJsonValueString>(TEXT("particle_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		if (!GEditor) return FConanMCPToolResult::Error(TEXT("Editor not available"));
		UWorld* World = GEditor->GetEditorWorldContext().World();
		if (!World) return FConanMCPToolResult::Error(TEXT("No active world"));

		FString ActorIdentifier = Arguments->GetStringField(TEXT("actor"));
		FString ParticlePath = Arguments->GetStringField(TEXT("particle_path"));
		FString SocketName = Arguments->GetStringField(TEXT("socket_name"));

		AActor* Actor = FindActorHelper(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		UObject* ParticleAsset = LoadObject<UObject>(nullptr, *ParticlePath);
		if (!ParticleAsset)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Particle asset '%s' not found"), *ParticlePath));
		}

		const FScopedTransaction Transaction(FText::FromString(FString::Printf(TEXT("ConanMCP: Preview Particle on %s"), *Actor->GetActorLabel())));
		Actor->Modify();

		USceneComponent* AttachParent = Actor->GetRootComponent();
		if (!SocketName.IsEmpty())
		{
			USkeletalMeshComponent* SkelMeshComp = Actor->FindComponentByClass<USkeletalMeshComponent>();
			if (SkelMeshComp && SkelMeshComp->DoesSocketExist(*SocketName))
			{
				AttachParent = SkelMeshComp;
			}
		}

		if (!AttachParent)
		{
			return FConanMCPToolResult::Error(TEXT("Actor has no root or attach component"));
		}

		FString CreatedCompName;
		if (UNiagaraSystem* NiagaraSys = Cast<UNiagaraSystem>(ParticleAsset))
		{
			UNiagaraComponent* NiagaraComp = NewObject<UNiagaraComponent>(Actor);
			NiagaraComp->SetAsset(NiagaraSys);
			NiagaraComp->ComponentTags.Add(CONAN_MCP_PREVIEW_TAG);
			NiagaraComp->SetupAttachment(AttachParent, !SocketName.IsEmpty() ? *SocketName : NAME_None);
			NiagaraComp->RegisterComponent();
			NiagaraComp->Activate(true);
			CreatedCompName = NiagaraComp->GetName();
		}
		else if (UParticleSystem* CascadeSys = Cast<UParticleSystem>(ParticleAsset))
		{
			UParticleSystemComponent* CascadeComp = NewObject<UParticleSystemComponent>(Actor);
			CascadeComp->SetTemplate(CascadeSys);
			CascadeComp->ComponentTags.Add(CONAN_MCP_PREVIEW_TAG);
			CascadeComp->SetupAttachment(AttachParent, !SocketName.IsEmpty() ? *SocketName : NAME_None);
			CascadeComp->RegisterComponent();
			CascadeComp->Activate(true);
			CreatedCompName = CascadeComp->GetName();
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());
		Data->SetStringField(TEXT("component_name"), CreatedCompName);
		Data->SetStringField(TEXT("attached_socket"), SocketName.IsEmpty() ? TEXT("Root") : SocketName);
		Data->SetBoolField(TEXT("success"), true);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: remove_preview_particle
// ============================================================================
class FRemovePreviewParticleTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("remove_preview_particle"); }
	virtual FString GetCategory() const override { return TEXT("Particles"); }
	virtual FString GetDescription() const override { return TEXT("Removes temporary preview particle components from an actor."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::SafeWrite; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> ActorProp = MakeShared<FJsonObject>();
		ActorProp->SetStringField(TEXT("type"), TEXT("string"));
		ActorProp->SetStringField(TEXT("description"), TEXT("Name or label of target actor"));
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
		AActor* Actor = FindActorHelper(World, ActorIdentifier);
		if (!Actor)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Actor '%s' not found"), *ActorIdentifier));
		}

		const FScopedTransaction Transaction(FText::FromString(FString::Printf(TEXT("ConanMCP: Remove Preview Particles from %s"), *Actor->GetActorLabel())));
		Actor->Modify();

		int32 RemovedCount = 0;
		TInlineComponentArray<UActorComponent*> Components(Actor);
		for (UActorComponent* Comp : Components)
		{
			if (Comp && Comp->ComponentTags.Contains(CONAN_MCP_PREVIEW_TAG))
			{
				Comp->DestroyComponent();
				RemovedCount++;
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("actor"), Actor->GetActorLabel());
		Data->SetNumberField(TEXT("removed_count"), RemovedCount);

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterParticleTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FFindParticleSystemsTool>());
	Registry.RegisterTool(MakeShared<FGetParticleInfoTool>());
	Registry.RegisterTool(MakeShared<FGetCharacterSocketsTool>());
	Registry.RegisterTool(MakeShared<FPreviewParticleOnActorTool>());
	Registry.RegisterTool(MakeShared<FRemovePreviewParticleTool>());
}
