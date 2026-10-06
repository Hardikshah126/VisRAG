import { useState, useCallback, useEffect, useRef } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Upload, FileText, CheckCircle2, Loader2, Image, Database, AlertCircle } from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiError, MAX_UPLOAD_MB, uploadPDF, waitUntilReady, type DocStage } from "@/lib/api";

export interface UploadedDocument {
  docId: string;
  filename: string;
}

interface UploadBoxProps {
  onUploadComplete: (doc: UploadedDocument) => void;
}

type Phase = "idle" | "uploading" | Exclude<DocStage, "failed"> | "error";

/** Where the progress bar sits while the backend works through each stage. */
const STAGE_PROGRESS: Record<Exclude<DocStage, "failed">, number> = {
  queued: 30,
  parsing: 40,
  extracting: 60,
  indexing: 85,
  complete: 100,
};

const phaseMessage: Record<Exclude<Phase, "idle" | "error">, string> = {
  uploading: "Uploading PDF...",
  queued: "Waiting for a free worker...",
  parsing: "Parsing text...",
  extracting: "Extracting tables & figures...",
  indexing: "Indexing in vector database...",
  complete: "Ready to chat ✅",
};

const phaseIcon = {
  uploading: Loader2,
  queued: Loader2,
  parsing: FileText,
  extracting: Image,
  indexing: Database,
  complete: CheckCircle2,
} as const;

function validate(file: File): string | null {
  const looksLikePdf = file.type === "application/pdf" || file.name.toLowerCase().endsWith(".pdf");
  if (!looksLikePdf) return "Only PDF files are supported.";
  if (file.size === 0) return "That file is empty.";
  if (file.size > MAX_UPLOAD_MB * 1024 * 1024) return `File is too large (max ${MAX_UPLOAD_MB}MB).`;
  return null;
}

export function UploadBox({ onUploadComplete }: UploadBoxProps) {
  const [isDragOver, setIsDragOver] = useState(false);
  const [phase, setPhase] = useState<Phase>("idle");
  const [progress, setProgress] = useState(0);
  const [fileName, setFileName] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Stop polling if the user navigates away mid-upload.
  useEffect(() => () => abortRef.current?.abort(), []);

  const reset = useCallback(() => {
    setPhase("idle");
    setProgress(0);
    setFileName(null);
    setError(null);
  }, []);

  const startUpload = useCallback(
    async (file: File) => {
      const problem = validate(file);
      if (problem) {
        setFileName(file.name);
        setError(problem);
        setPhase("error");
        return;
      }

      const controller = new AbortController();
      abortRef.current = controller;
      setFileName(file.name);
      setError(null);
      setProgress(0);
      setPhase("uploading");

      try {
        // Real upload progress, scaled into the first 30% of the bar.
        const { doc_id, filename } = await uploadPDF(file, (fraction) => setProgress(Math.round(fraction * 30)));

        await waitUntilReady(
          doc_id,
          (stage) => {
            if (stage === "failed") return;
            setPhase(stage);
            setProgress(STAGE_PROGRESS[stage]);
          },
          { signal: controller.signal },
        );

        setPhase("complete");
        setProgress(100);
        await new Promise((r) => setTimeout(r, 600));
        onUploadComplete({ docId: doc_id, filename });
      } catch (err) {
        if ((err as Error).name === "AbortError") return;
        setError(err instanceof ApiError ? err.message : "Something went wrong while uploading.");
        setPhase("error");
      }
    },
    [onUploadComplete],
  );

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragOver(false);
      const file = e.dataTransfer.files[0];
      if (file) void startUpload(file);
    },
    [startUpload],
  );

  const handleFileInput = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-selecting the same file after an error
      if (file) void startUpload(file);
    },
    [startUpload],
  );

  const isProcessing = phase !== "idle" && phase !== "complete" && phase !== "error";
  const showForm = phase === "idle";
  const StatusIcon = phase === "idle" || phase === "error" ? null : phaseIcon[phase];

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.5 }}
      className="w-full max-w-2xl mx-auto"
    >
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setIsDragOver(true);
        }}
        onDragLeave={() => setIsDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "upload-zone",
          showForm && "cursor-pointer",
          isDragOver && "dragover",
          isProcessing && "pointer-events-none",
        )}
      >
        {showForm && (
          <input
            type="file"
            accept=".pdf,application/pdf"
            onChange={handleFileInput}
            aria-label="Upload a PDF"
            className="absolute inset-0 opacity-0 cursor-pointer"
          />
        )}

        <AnimatePresence mode="wait">
          {showForm ? (
            <motion.div
              key="idle"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-4"
            >
              <motion.div
                animate={{ y: isDragOver ? -8 : 0 }}
                transition={{ type: "spring", stiffness: 300 }}
                className="flex items-center justify-center w-16 h-16 rounded-2xl bg-primary/10"
              >
                <Upload className="w-8 h-8 text-primary" />
              </motion.div>
              <div className="text-center">
                <h3 className="text-lg font-semibold text-foreground mb-1">Drop your PDF here</h3>
                <p className="text-sm text-muted-foreground">
                  or click to browse • Biology books, reports, research papers
                </p>
              </div>
              <div className="flex items-center gap-2 mt-2">
                <span className="px-3 py-1 text-xs font-medium rounded-full bg-secondary text-muted-foreground">
                  .PDF
                </span>
                <span className="px-3 py-1 text-xs font-medium rounded-full bg-secondary text-muted-foreground">
                  Max {MAX_UPLOAD_MB}MB
                </span>
              </div>
            </motion.div>
          ) : (
            <motion.div
              key="processing"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              className="flex flex-col items-center gap-6 py-4"
            >
              <div className="flex items-center gap-2 px-4 py-2 rounded-lg bg-secondary">
                <FileText className="w-4 h-4 text-primary" />
                <span className="text-sm font-medium text-foreground truncate max-w-[300px]">{fileName}</span>
              </div>

              {phase === "error" ? (
                <div role="alert" className="flex flex-col items-center gap-4 text-center">
                  <div className="flex items-center gap-2 text-destructive">
                    <AlertCircle className="w-5 h-5" />
                    <span className="text-sm font-medium">{error}</span>
                  </div>
                  <button
                    type="button"
                    onClick={reset}
                    className="px-4 py-2 text-sm font-medium rounded-lg bg-primary text-primary-foreground hover:opacity-90 pointer-events-auto"
                  >
                    Try another file
                  </button>
                </div>
              ) : (
                <>
                  <div className="w-full max-w-md">
                    <div
                      className="progress-bar h-2"
                      role="progressbar"
                      aria-valuemin={0}
                      aria-valuemax={100}
                      aria-valuenow={progress}
                    >
                      <motion.div
                        className="h-full rounded-full bg-primary"
                        initial={{ width: 0 }}
                        animate={{ width: `${progress}%` }}
                        transition={{ duration: 0.3 }}
                      />
                    </div>
                  </div>

                  <motion.div
                    key={phase}
                    initial={{ opacity: 0, y: 10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="flex items-center gap-2"
                  >
                    {StatusIcon && (
                      <StatusIcon
                        className={cn("w-5 h-5", phase === "complete" ? "text-success" : "text-primary animate-spin")}
                      />
                    )}
                    <span
                      className={cn("text-sm font-medium", phase === "complete" ? "text-success" : "text-foreground")}
                    >
                      {phaseMessage[phase as keyof typeof phaseMessage]}
                    </span>
                  </motion.div>

                  <div className="flex items-center gap-6 mt-2">
                    {[
                      { icon: FileText, label: "Parse", done: ["extracting", "indexing", "complete"].includes(phase) },
                      { icon: Image, label: "Extract", done: ["indexing", "complete"].includes(phase) },
                      { icon: Database, label: "Index", done: phase === "complete" },
                    ].map((step) => (
                      <div key={step.label} className="flex flex-col items-center gap-1">
                        <div
                          className={cn(
                            "w-8 h-8 rounded-lg flex items-center justify-center transition-colors",
                            step.done ? "bg-success/10 text-success" : "bg-secondary text-muted-foreground",
                          )}
                        >
                          <step.icon className="w-4 h-4" />
                        </div>
                        <span className="text-xs text-muted-foreground">{step.label}</span>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </motion.div>
  );
}
