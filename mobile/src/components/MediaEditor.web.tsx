import { useI18n, translate } from "@/i18n";
import AsyncStorage from "@react-native-async-storage/async-storage";
import { writeAccountDraft } from "@/lib/accountDrafts";
import React from "react";
import EditorSurface from "./EditorSurface";
import type { MediaEditorProps } from "./MediaEditor";
export function MediaEditor({source,photo,onClose,draftKey,saveCreation,openCreation,mimeType,onScenes,scenes}:MediaEditorProps) {
 const { locale } = useI18n();
 return <EditorSurface locale={locale} source={source} photo={photo} draftKey={draftKey} saveCreation={saveCreation} openCreation={openCreation} onScenes={onScenes} scenes={scenes}
  onClose={async()=>onClose()} loadDraft={()=>AsyncStorage.getItem(draftKey)}
  saveDraft={value=>writeAccountDraft(draftKey,value)} />;
}
