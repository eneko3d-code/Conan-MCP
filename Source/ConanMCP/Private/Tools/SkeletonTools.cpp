#include "ConanMCPTool.h"
#include "ConanMCPToolRegistry.h"
#include "ConanMCPModule.h"
#include "Engine/SkeletalMesh.h"
#include "Engine/SkeletalMeshSocket.h"
#include "Animation/Skeleton.h"
#include "ReferenceSkeleton.h"

// ============================================================================
// Tool: get_skeletal_mesh_info
// ============================================================================
class FGetSkeletalMeshInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_skeletal_mesh_info"); }
	virtual FString GetCategory() const override { return TEXT("Skeleton"); }
	virtual FString GetDescription() const override { return TEXT("Returns Skeletal Mesh details: skeleton asset, materials, LOD count, and bone count."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Skeletal Mesh asset path (e.g. '/Game/Characters/SK_Hero')"));
		Props->SetObjectField(TEXT("mesh_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("mesh_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString MeshPath = Arguments->GetStringField(TEXT("mesh_path"));
		USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, *MeshPath);
		if (!Mesh)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load SkeletalMesh at '%s'"), *MeshPath));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("mesh_name"), Mesh->GetName());
		Data->SetStringField(TEXT("skeleton"), Mesh->GetSkeleton() ? Mesh->GetSkeleton()->GetName() : TEXT("None"));
		Data->SetStringField(TEXT("skeleton_path"), Mesh->GetSkeleton() ? Mesh->GetSkeleton()->GetPathName() : TEXT("None"));
		Data->SetNumberField(TEXT("lod_count"), Mesh->GetLODNum());

		const FReferenceSkeleton& RefSkeleton = Mesh->GetRefSkeleton();
		Data->SetNumberField(TEXT("bone_count"), RefSkeleton.GetNum());

		TArray<TSharedPtr<FJsonValue>> MatList;
		for (const FSkeletalMaterial& Mat : Mesh->GetMaterials())
		{
			TSharedPtr<FJsonObject> MatObj = MakeShared<FJsonObject>();
			MatObj->SetStringField(TEXT("slot_name"), Mat.MaterialSlotName.ToString());
			MatObj->SetStringField(TEXT("material"), Mat.MaterialInterface ? Mat.MaterialInterface->GetName() : TEXT("None"));
			MatList.Add(MakeShared<FJsonValueObject>(MatObj));
		}
		Data->SetArrayField(TEXT("materials"), MatList);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_skeleton_info
// ============================================================================
class FGetSkeletonInfoTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_skeleton_info"); }
	virtual FString GetCategory() const override { return TEXT("Skeleton"); }
	virtual FString GetDescription() const override { return TEXT("Returns bone count, virtual bones, and socket count for a Skeleton asset."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("Skeleton asset path"));
		Props->SetObjectField(TEXT("skeleton_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("skeleton_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString SkeletonPath = Arguments->GetStringField(TEXT("skeleton_path"));
		USkeleton* Skeleton = LoadObject<USkeleton>(nullptr, *SkeletonPath);
		if (!Skeleton)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load Skeleton at '%s'"), *SkeletonPath));
		}

		const FReferenceSkeleton& RefSkeleton = Skeleton->GetReferenceSkeleton();
		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("skeleton_name"), Skeleton->GetName());
		Data->SetNumberField(TEXT("bone_count"), RefSkeleton.GetNum());
		Data->SetNumberField(TEXT("socket_count"), Skeleton->Sockets.Num());

		TArray<TSharedPtr<FJsonValue>> SocketsList;
		for (USkeletalMeshSocket* Socket : Skeleton->Sockets)
		{
			if (Socket)
			{
				SocketsList.Add(MakeShared<FJsonValueString>(Socket->SocketName.ToString()));
			}
		}
		Data->SetArrayField(TEXT("sockets"), SocketsList);

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_skeleton_sockets
// ============================================================================
class FGetSkeletonSocketsTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_skeleton_sockets"); }
	virtual FString GetCategory() const override { return TEXT("Skeleton"); }
	virtual FString GetDescription() const override { return TEXT("Lists all sockets on a Skeleton or Skeletal Mesh with attach bone and relative transform."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("SkeletalMesh or Skeleton asset path"));
		Props->SetObjectField(TEXT("asset_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("asset_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString AssetPath = Arguments->GetStringField(TEXT("asset_path"));
		USkeleton* Skeleton = LoadObject<USkeleton>(nullptr, *AssetPath);
		USkeletalMesh* Mesh = nullptr;

		if (!Skeleton)
		{
			Mesh = LoadObject<USkeletalMesh>(nullptr, *AssetPath);
			if (Mesh)
			{
				Skeleton = Mesh->GetSkeleton();
			}
		}

		if (!Skeleton && !Mesh)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Could not load Skeleton or SkeletalMesh at '%s'"), *AssetPath));
		}

		TArray<TSharedPtr<FJsonValue>> SocketsList;

		auto AddSocketInfo = [&SocketsList](USkeletalMeshSocket* Socket)
		{
			if (!Socket) return;
			TSharedPtr<FJsonObject> SockObj = MakeShared<FJsonObject>();
			SockObj->SetStringField(TEXT("socket_name"), Socket->SocketName.ToString());
			SockObj->SetStringField(TEXT("bone_name"), Socket->BoneName.ToString());

			TSharedPtr<FJsonObject> LocObj = MakeShared<FJsonObject>();
			LocObj->SetNumberField(TEXT("x"), Socket->RelativeLocation.X);
			LocObj->SetNumberField(TEXT("y"), Socket->RelativeLocation.Y);
			LocObj->SetNumberField(TEXT("z"), Socket->RelativeLocation.Z);
			SockObj->SetObjectField(TEXT("relative_location"), LocObj);

			TSharedPtr<FJsonObject> RotObj = MakeShared<FJsonObject>();
			RotObj->SetNumberField(TEXT("pitch"), Socket->RelativeRotation.Pitch);
			RotObj->SetNumberField(TEXT("yaw"), Socket->RelativeRotation.Yaw);
			RotObj->SetNumberField(TEXT("roll"), Socket->RelativeRotation.Roll);
			SockObj->SetObjectField(TEXT("relative_rotation"), RotObj);

			SocketsList.Add(MakeShared<FJsonValueObject>(SockObj));
		};

		if (Skeleton)
		{
			for (USkeletalMeshSocket* Socket : Skeleton->Sockets)
			{
				AddSocketInfo(Socket);
			}
		}

		if (Mesh)
		{
			for (USkeletalMeshSocket* Socket : Mesh->GetMeshOnlySocketList())
			{
				AddSocketInfo(Socket);
			}
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetArrayField(TEXT("sockets"), SocketsList);
		Data->SetNumberField(TEXT("count"), SocketsList.Num());

		return FConanMCPToolResult::Success(Data);
	}
};

// ============================================================================
// Tool: get_bones
// ============================================================================
class FGetBonesTool : public IConanMCPTool
{
public:
	virtual FString GetName() const override { return TEXT("get_bones"); }
	virtual FString GetCategory() const override { return TEXT("Skeleton"); }
	virtual FString GetDescription() const override { return TEXT("Returns bone hierarchy tree (name, parent index, bone index) of a Skeletal Mesh."); }
	virtual EConanMCPSecurityLevel GetSecurityLevel() const override { return EConanMCPSecurityLevel::ReadOnly; }

	virtual TSharedPtr<FJsonObject> GetInputSchema() const override
	{
		TSharedPtr<FJsonObject> Schema = MakeShared<FJsonObject>();
		Schema->SetStringField(TEXT("type"), TEXT("object"));

		TSharedPtr<FJsonObject> Props = MakeShared<FJsonObject>();
		TSharedPtr<FJsonObject> PathProp = MakeShared<FJsonObject>();
		PathProp->SetStringField(TEXT("type"), TEXT("string"));
		PathProp->SetStringField(TEXT("description"), TEXT("SkeletalMesh asset path"));
		Props->SetObjectField(TEXT("mesh_path"), PathProp);

		Schema->SetObjectField(TEXT("properties"), Props);
		TArray<TSharedPtr<FJsonValue>> Req;
		Req.Add(MakeShared<FJsonValueString>(TEXT("mesh_path")));
		Schema->SetArrayField(TEXT("required"), Req);

		return Schema;
	}

	virtual FConanMCPToolResult Execute(const TSharedPtr<FJsonObject>& Arguments) override
	{
		FString MeshPath = Arguments->GetStringField(TEXT("mesh_path"));
		USkeletalMesh* Mesh = LoadObject<USkeletalMesh>(nullptr, *MeshPath);
		if (!Mesh)
		{
			return FConanMCPToolResult::Error(FString::Printf(TEXT("Failed to load SkeletalMesh at '%s'"), *MeshPath));
		}

		const FReferenceSkeleton& RefSkeleton = Mesh->GetRefSkeleton();
		TArray<TSharedPtr<FJsonValue>> BonesList;

		for (int32 i = 0; i < RefSkeleton.GetNum(); i++)
		{
			TSharedPtr<FJsonObject> BoneObj = MakeShared<FJsonObject>();
			BoneObj->SetNumberField(TEXT("index"), i);
			BoneObj->SetStringField(TEXT("name"), RefSkeleton.GetBoneName(i).ToString());
			int32 ParentIndex = RefSkeleton.GetParentIndex(i);
			BoneObj->SetNumberField(TEXT("parent_index"), ParentIndex);
			BoneObj->SetStringField(TEXT("parent_name"), ParentIndex >= 0 ? RefSkeleton.GetBoneName(ParentIndex).ToString() : TEXT("Root"));

			BonesList.Add(MakeShared<FJsonValueObject>(BoneObj));
		}

		TSharedPtr<FJsonObject> Data = MakeShared<FJsonObject>();
		Data->SetStringField(TEXT("mesh"), Mesh->GetName());
		Data->SetNumberField(TEXT("bone_count"), BonesList.Num());
		Data->SetArrayField(TEXT("bones"), BonesList);

		return FConanMCPToolResult::Success(Data);
	}
};

void RegisterSkeletonTools(FConanMCPToolRegistry& Registry)
{
	Registry.RegisterTool(MakeShared<FGetSkeletalMeshInfoTool>());
	Registry.RegisterTool(MakeShared<FGetSkeletonInfoTool>());
	Registry.RegisterTool(MakeShared<FGetSkeletonSocketsTool>());
	Registry.RegisterTool(MakeShared<FGetBonesTool>());
}
