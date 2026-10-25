import { useQueryClient } from "@tanstack/react-query";
import { useContext, useEffect, useMemo, useState } from "react";
import { Outlet, useLocation } from "react-router-dom";

import SideBarFoldersButtonsComponent from "@/components/core/folderSidebarComponent/components/sideBarFolderButtons";
import { SidebarProvider } from "@/components/ui/sidebar";
import CustomEmptyPageCommunity from "@/customization/components/custom-empty-page";
import CustomLoader from "@/customization/components/custom-loader";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import AccessDeniedPage from "@/pages/AccessDeniedPage";

import useAlertStore from "@/stores/alertStore";
import useAgentsManagerStore from "@/stores/agentsManagerStore";
import { useFolderStore } from "@/stores/foldersStore";

import ModalsComponent from "../components/modalsComponent";
import FolderCardsView from "./folderCollections/folder-cards-view";
import EditFolderModal from "./folderCollections/edit-folder-modal";

import {
  useDeleteFolders,
  usePatchFolders,
} from "@/controllers/API/queries/folders";
import { AuthContext } from "@/contexts/authContext";

export default function CollectionPage(): JSX.Element {
  /* ================= STATE ================= */

  const [openModal, setOpenModal] = useState(false);
  const [openDeleteFolderModal, setOpenDeleteFolderModal] = useState(false);
  const [openEditFolderModal, setOpenEditFolderModal] = useState(false);

  const navigate = useCustomNavigate();
  const location = useLocation();
  const queryClient = useQueryClient();
  const { permissions, role } = useContext(AuthContext);

  /* ================= STORES ================= */

  const agents = useAgentsManagerStore((s) => s.agents);
  const examples = useAgentsManagerStore((s) => s.examples);

  const folders = useFolderStore((s) => s.folders);
  const folderToEdit = useFolderStore((s) => s.folderToEdit);
  const setFolderToEdit = useFolderStore((s) => s.setFolderToEdit);

  const setSuccessData = useAlertStore((s) => s.setSuccessData);
  const setErrorData = useAlertStore((s) => s.setErrorData);

  /* ================= ROUTE DETECTION ================= */

  const isAgentsRoute =
    location.pathname === "/agents" || location.pathname === "/agents/";

  const isInAgentsFolder = location.pathname.includes("/agents/folder/");

  /* ================= CLEANUP ================= */

  useEffect(() => {
    return () => {
      queryClient.removeQueries({ queryKey: ["useGetFolder"] });
    };
  }, [queryClient]);

  /* ================= API MUTATIONS ================= */

  const { mutate: deleteFolder } = useDeleteFolders();
  const { mutate: updateFolder } = usePatchFolders();

  const handleDeleteFolder = () => {
    if (!folderToEdit) return;

    deleteFolder(
      { project_id: folderToEdit.id },
      {
        onSuccess: () => {
          setSuccessData({ title: "Project deleted successfully." });
          navigate("/agents");
        },
        onError: (error: any) => {
          const detail =
            error?.response?.data?.detail ||
            error?.message ||
            "Error deleting project.";
          setErrorData({
            title: "Error deleting project.",
            list: detail ? [String(detail)] : undefined,
          });
        },
      },
    );
  };

  const handleUpdateFolderName = (newName: string, newDescription: string, tags?: string[]) => {
    if (!folderToEdit || !newName.trim()) return;

    updateFolder(
      {
        folderId: folderToEdit.id,
        data: {
          ...folderToEdit,
          name: newName.trim(),
          description: newDescription,
          agents: folderToEdit.agents ?? [],
          components: folderToEdit.components ?? [],
          tags: tags ?? folderToEdit.tags ?? [],
        },
      },
      {
        onSuccess: () => {
          setSuccessData({ title: "Project updated successfully." });
          setOpenEditFolderModal(false);
          setFolderToEdit(undefined);
        },
        onError: () => {
          setErrorData({ title: "Error renaming project." });
        },
      },
    );
  };

  /* ================= DERIVED STATE ================= */

  const hasContent = Boolean(agents && examples && folders);

  const showEmptyState =
    hasContent &&
    folders.length === 0 &&
    !new URLSearchParams(location.search).has("openCreateProject");

  const isRegistryPreviewRoute = /^\/agent-catalogue\/[^/]+\/view\/?$/.test(
    location.pathname,
  );
  const isReadOnlyAgentRoute =
    location.pathname.startsWith("/agent/") &&
    new URLSearchParams(location.search).get("readonly") === "1";
  const showSidebar = !(isRegistryPreviewRoute || isReadOnlyAgentRoute);
  const requiredPagePermission = useMemo(() => {
    const pathname = location.pathname;
    if (
      pathname === "/agents" ||
      pathname === "/agents/" ||
      pathname.startsWith("/agents/folder/") ||
      pathname === "/components" ||
      pathname === "/components/" ||
      pathname.startsWith("/components/folder/") ||
      pathname === "/all" ||
      pathname === "/all/" ||
      pathname.startsWith("/all/folder/") ||
      pathname === "/mcp" ||
      pathname === "/mcp/" ||
      pathname.startsWith("/mcp/folder/")
    ) {
      return "view_projects_page";
    }
    if (pathname === "/help-support" || pathname === "/help-support/") {
      return "view_help_support_page";
    }
    if (pathname === "/assets/knowledge-bases" || pathname === "/assets/knowledge-bases/") {
      return "view_knowledge_base";
    }
    return null;
  }, [location.pathname]);
  const isRootUser = String(role ?? "").toLowerCase() === "root";
  const hasRequiredPagePermission =
    !requiredPagePermission || isRootUser || permissions?.includes(requiredPagePermission);

  /* ================= SHARED SIDEBAR ================= */

  const Sidebar = showSidebar ? (
    <SideBarFoldersButtonsComponent
      handleChangeFolder={(id: string) => {
        navigate(`/agents/folder/${id}`);
      }}
      handleDeleteFolder={(folder) => {
        setFolderToEdit(folder);
        setOpenDeleteFolderModal(true);
      }}
      handleFilesClick={() => {
        navigate("/assets/files");
      }}
    />
  ) : null;

  /* ================= LAYOUT ================= */

  return (
    <SidebarProvider width="280px">
      {Sidebar}

      <main className="flex h-full w-full overflow-hidden">
        {!hasRequiredPagePermission ? (
          <div className="relative mx-auto flex h-full w-full flex-col overflow-hidden">
            <AccessDeniedPage message={`Missing permission: ${requiredPagePermission}`} />
          </div>
        ) : !hasContent ? (
          <div className="flex h-full w-full items-center justify-center">
            <CustomLoader remSize={30} />
          </div>
        ) : isAgentsRoute ? (
          <div className="relative mx-auto flex h-full w-full flex-col overflow-hidden">
            {showEmptyState ? (
              <CustomEmptyPageCommunity
                setOpenModal={() => {
                  navigate("/agents?openCreateProject=1");
                }}
              />
            ) : (
              <FolderCardsView
                setOpenModal={setOpenModal}
                onFolderClick={(folderId: string) => {
                  navigate(`/agents/folder/${folderId}`);
                }}
                onRenameFolder={(folder) => {
                  setFolderToEdit(folder);
                  setOpenEditFolderModal(true);
                }}
                onDeleteFolder={(folder) => {
                  setFolderToEdit(folder);
                  setOpenDeleteFolderModal(true);
                }}
                // onFilesClick={() => {
                //   navigate("/assets/files");
                // }}
              />
            )}
          </div>
        ) : (
          <div className="relative mx-auto flex h-full w-full flex-col overflow-hidden">
            <Outlet />
          </div>
        )}
      </main>

      <ModalsComponent
        openModal={openModal}
        setOpenModal={setOpenModal}
        openDeleteFolderModal={openDeleteFolderModal}
        setOpenDeleteFolderModal={setOpenDeleteFolderModal}
        handleDeleteFolder={handleDeleteFolder}
      />
      <EditFolderModal
        open={openEditFolderModal}
        setOpen={setOpenEditFolderModal}
        folder={folderToEdit}
        onSave={handleUpdateFolderName}
      />

      <EditFolderModal
        open={openEditFolderModal}
        setOpen={setOpenEditFolderModal}
        folder={folderToEdit}
        onSave={handleUpdateFolderName}
      />
    </SidebarProvider>
  );
}
