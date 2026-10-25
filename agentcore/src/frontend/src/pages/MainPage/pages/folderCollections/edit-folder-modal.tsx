import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import TagInput from "@/components/common/tagInputComponent";
import type { FolderType } from "@/pages/MainPage/entities";

interface EditFolderModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
  folder?: FolderType;
  onSave: (newName: string, newDescription: string, tags: string[]) => void;
}

export default function EditFolderModal({
  open,
  setOpen,
  folder,
  onSave,
}: EditFolderModalProps): JSX.Element {
  const [folderName, setFolderName] = useState("");
  const [folderDescription, setFolderDescription] = useState("");
  const [folderTags, setFolderTags] = useState<string[]>([]);

  useEffect(() => {
    if (folder) {
      setFolderName(folder.name);
      setFolderDescription(folder.description || "");
      setFolderTags(folder.tags ?? []);
    }
  }, [folder]);

  const handleSave = () => {
    if (folderName.trim()) {
      onSave(folderName, folderDescription.trim(), folderTags);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && e.target instanceof HTMLInputElement && e.target.id !== "tag-input") {
      handleSave();
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{folder ? "Edit Project" : "Create Project"}</DialogTitle>
          <DialogDescription>
            {folder ? "Update your project details" : "Enter details for your new project"}
          </DialogDescription>
        </DialogHeader>
        <div className="grid gap-4 py-4">
          <div className="grid gap-2">
            <Label htmlFor="name">Project Name</Label>
            <Input
              id="name"
              value={folderName}
              onChange={(e) => setFolderName(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Enter project name"
              autoFocus
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="description">Description (Optional)</Label>
            <Input
              id="description"
              value={folderDescription}
              onChange={(e) => setFolderDescription(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Brief description of your project..."
            />
          </div>
          <div className="grid gap-2">
            <Label>Tags</Label>
            <TagInput
              selectedTags={folderTags}
              onChange={setFolderTags}
              placeholder="Add tags (e.g. rag, chatbot, finance)..."
              maxTags={10}
            />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button onClick={handleSave} disabled={!folderName.trim()}>
            Save
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
