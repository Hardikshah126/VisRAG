/** Backend API client. */

export const API_URL = (import.meta.env.VITE_API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, "");
const API_KEY: string | undefined = import.meta.env.VITE_API_KEY || undefined;

/** Keep in sync with the backend's MAX_UPLOAD_MB. */
export const MAX_UPLOAD_MB = 25;

export class ApiError extends Error {
  constructor(
    message: string,
    public status?: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export type DocStage = "queued" | "parsing" | "extracting" | "indexing" | "complete" | "failed";

export interface UploadResult {
  doc_id: string;
  filename: string;
  status: "processing";
}

export interface DocStatus {
  doc_id: string;
  filename?: string | null;
  status: "processing" | "ready" | "failed";
  stage?: DocStage | null;
  blocks?: number | null;
  error?: string | null;
}

export interface ChatTurn {
  role: "user" | "assistant";
  content: string;
}

export interface AskResult {
  answer: string;
  citations: number[];
  supporting_visuals: {
    id: string;
    type: "image" | "table";
    page: number;
    caption?: string | null;
    src?: string | null;
    tableData?: string[][] | null;
  }[];
  doc_id: string;
}

function authHeaders(): Record<string, string> {
  return API_KEY ? { "X-API-Key": API_KEY } : {};
}

/** Image paths come back relative to the API ("/extracted/..."). */
export function resolveAssetUrl(src?: string | null): string | undefined {
  if (!src) return undefined;
  return /^https?:\/\//i.test(src) ? src : `${API_URL}${src}`;
}

/** Turn FastAPI's `{detail: "..."}` / validation-error payloads into a message. */
export function messageFromBody(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string" && detail) return detail;
  if (Array.isArray(detail) && detail.length > 0) {
    const first = detail[0] as { msg?: string };
    if (first?.msg) return first.msg;
  }
  return fallback;
}

async function failure(res: Response, fallback: string): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await res.json();
  } catch {
    /* non-JSON error body */
  }
  const message =
    res.status === 429
      ? "Too many requests. Please wait a moment and try again."
      : messageFromBody(body, `${fallback} (HTTP ${res.status})`);
  return new ApiError(message, res.status);
}

async function request(path: string, init: RequestInit, fallback: string): Promise<Response> {
  let res: Response;
  try {
    res = await fetch(`${API_URL}${path}`, {
      ...init,
      headers: { ...authHeaders(), ...(init.headers as Record<string, string> | undefined) },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Cannot reach the server. Is the backend running?");
  }
  if (!res.ok) throw await failure(res, fallback);
  return res;
}

/** Upload a PDF with real progress (fetch cannot report upload progress). */
export function uploadPDF(file: File, onProgress?: (fraction: number) => void): Promise<UploadResult> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_URL}/upload`);
    for (const [key, value] of Object.entries(authHeaders())) xhr.setRequestHeader(key, value);

    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(e.loaded / e.total);
    };
    xhr.onerror = () => reject(new ApiError("Cannot reach the server. Is the backend running?"));
    xhr.onabort = () => reject(new DOMException("Upload cancelled", "AbortError"));
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        /* non-JSON body */
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as UploadResult);
      } else {
        const message =
          xhr.status === 429
            ? "Too many requests. Please wait a moment and try again."
            : messageFromBody(body, `Upload failed (HTTP ${xhr.status})`);
        reject(new ApiError(message, xhr.status));
      }
    };

    const form = new FormData();
    form.append("file", file);
    xhr.send(form);
  });
}

export async function getStatus(docId: string, signal?: AbortSignal): Promise<DocStatus> {
  const res = await request(`/status/${docId}`, { signal }, "Could not check document status");
  return res.json();
}

/**
 * Poll until the backend finishes ingesting the document. Resolves when ready;
 * rejects with the backend's message if processing failed.
 */
export async function waitUntilReady(
  docId: string,
  onStage?: (stage: DocStage) => void,
  { signal, intervalMs = 1000, timeoutMs = 10 * 60 * 1000 }: { signal?: AbortSignal; intervalMs?: number; timeoutMs?: number } = {},
): Promise<DocStatus> {
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const status = await getStatus(docId, signal);
    if (status.stage) onStage?.(status.stage);
    if (status.status === "ready") return status;
    if (status.status === "failed") throw new ApiError(status.error || "Failed to process the PDF.");
    if (Date.now() > deadline) throw new ApiError("Processing is taking too long. Please try again.");
    await new Promise<void>((resolve, reject) => {
      if (signal?.aborted) return reject(new DOMException("Cancelled", "AbortError"));
      const onAbort = () => {
        clearTimeout(timer);
        reject(new DOMException("Cancelled", "AbortError"));
      };
      const timer = setTimeout(() => {
        signal?.removeEventListener("abort", onAbort);
        resolve();
      }, intervalMs);
      signal?.addEventListener("abort", onAbort, { once: true });
    });
  }
}

export async function askQuestion(
  query: string,
  docId: string,
  history: ChatTurn[] = [],
  signal?: AbortSignal,
): Promise<AskResult> {
  const res = await request(
    "/ask",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, doc_id: docId, history }),
      signal,
    },
    "Could not get an answer",
  );
  return res.json();
}

export async function deleteDocument(docId: string): Promise<void> {
  await request(`/documents/${docId}`, { method: "DELETE" }, "Could not delete the document");
}

export async function checkHealth(): Promise<boolean> {
  const res = await request("/health", {}, "Backend unreachable");
  const body = await res.json();
  return body.status === "ok";
}
