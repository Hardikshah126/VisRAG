import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";

import { MessageBubble } from "@/components/MessageBubble";
import { VisualPanel } from "@/components/VisualPanel";
import { UploadBox } from "@/components/UploadBox";
import { ChatWindow } from "@/components/ChatWindow";
import { ErrorBoundary } from "@/components/ErrorBoundary";
import * as api from "@/lib/api";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

const msg = (content: string, extra = {}) => ({
  id: "1",
  role: "assistant" as const,
  content,
  timestamp: new Date(),
  ...extra,
});

describe("MessageBubble", () => {
  it("renders markdown from the model (bold, lists)", () => {
    render(<MessageBubble message={msg("**Revenue** grew:\n\n* North\n* South")} />);
    expect(screen.getByText("Revenue").tagName).toBe("STRONG");
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
  });

  it("does not render raw HTML from the model", () => {
    const { container } = render(<MessageBubble message={msg('<img src=x onerror="alert(1)"> hi <script>x()</script>')} />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("shows errors as an alert", () => {
    render(<MessageBubble message={msg("Document is still being processed.", { isError: true })} />);
    expect(screen.getByRole("alert")).toHaveTextContent("still being processed");
  });
});

describe("VisualPanel", () => {
  it("does not crash on an empty table (it used to blank the whole app)", () => {
    render(<VisualPanel visuals={[{ id: "t", type: "table", page: 1, tableData: [] }]} />);
    expect(screen.getByText("Table data not available.")).toBeInTheDocument();
  });

  it("renders table cells, including non-string values", () => {
    render(
      <VisualPanel
        visuals={[{ id: "t", type: "table", page: 2, tableData: [["Region", "Q1"], ["North", 120 as unknown as string]] }]}
      />,
    );
    expect(screen.getByText("North")).toBeInTheDocument();
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("resolves relative image paths against the API origin and falls back when the file is missing", () => {
    render(<VisualPanel visuals={[{ id: "i", type: "image", page: 3, src: "/extracted/abc/f.png", caption: "Fig" }]} />);
    const img = screen.getByRole("img", { name: "Fig" });
    expect(img).toHaveAttribute("src", `${api.API_URL}/extracted/abc/f.png`);
    fireEvent.error(img);
    expect(screen.getByText("Image not available")).toBeInTheDocument();
  });
});

describe("UploadBox", () => {
  const pdf = (name = "report.pdf", size = 1000) => {
    const file = new File(["x"], name, { type: "application/pdf" });
    Object.defineProperty(file, "size", { value: size });
    return file;
  };
  const input = () => screen.getByLabelText("Upload a PDF") as HTMLInputElement;

  it("really uploads the file and hands over the server-issued doc id (not the filename)", async () => {
    const upload = vi
      .spyOn(api, "uploadPDF")
      .mockResolvedValue({ doc_id: "a".repeat(32), filename: "My_Report_1_.pdf", status: "processing" });
    vi.spyOn(api, "waitUntilReady").mockImplementation(async (_id, onStage) => {
      onStage?.("indexing");
      return { doc_id: "a".repeat(32), status: "ready" };
    });
    const onDone = vi.fn();

    render(<UploadBox onUploadComplete={onDone} />);
    const file = pdf("My Report (1).pdf");
    await userEvent.upload(input(), file);

    expect(upload).toHaveBeenCalledWith(file, expect.any(Function));
    await waitFor(() => expect(onDone).toHaveBeenCalled(), { timeout: 3000 });
    expect(onDone).toHaveBeenCalledWith({ docId: "a".repeat(32), filename: "My_Report_1_.pdf" });
  });

  it("rejects non-PDF files with a message instead of silently ignoring them", async () => {
    const upload = vi.spyOn(api, "uploadPDF");
    render(<UploadBox onUploadComplete={vi.fn()} />);
    fireEvent.change(input(), { target: { files: [new File(["x"], "notes.txt", { type: "text/plain" })] } });
    expect(await screen.findByRole("alert")).toHaveTextContent("Only PDF files");
    expect(upload).not.toHaveBeenCalled();
  });

  it("rejects oversize files before uploading", async () => {
    const upload = vi.spyOn(api, "uploadPDF");
    render(<UploadBox onUploadComplete={vi.fn()} />);
    fireEvent.change(input(), { target: { files: [pdf("big.pdf", (api.MAX_UPLOAD_MB + 1) * 1024 * 1024)] } });
    expect(await screen.findByRole("alert")).toHaveTextContent(`max ${api.MAX_UPLOAD_MB}MB`);
    expect(upload).not.toHaveBeenCalled();
  });

  it("shows the backend's failure reason and lets the user retry", async () => {
    vi.spyOn(api, "uploadPDF").mockRejectedValue(new api.ApiError("File is not a valid PDF.", 400));
    render(<UploadBox onUploadComplete={vi.fn()} />);
    await userEvent.upload(input(), pdf());
    expect(await screen.findByRole("alert")).toHaveTextContent("File is not a valid PDF.");

    await userEvent.click(screen.getByRole("button", { name: "Try another file" }));
    expect(input()).toBeInTheDocument();
  });

  it("surfaces ingestion failures reported by the status endpoint", async () => {
    vi.spyOn(api, "uploadPDF").mockResolvedValue({ doc_id: "b".repeat(32), filename: "scan.pdf", status: "processing" });
    vi.spyOn(api, "waitUntilReady").mockRejectedValue(new api.ApiError("Scanned PDFs need OCR."));
    render(<UploadBox onUploadComplete={vi.fn()} />);
    await userEvent.upload(input(), pdf("scan.pdf"));
    expect(await screen.findByRole("alert")).toHaveTextContent("Scanned PDFs need OCR.");
  });
});

describe("ChatWindow", () => {
  const answer = (text: string): api.AskResult => ({
    answer: text,
    citations: [2],
    supporting_visuals: [],
    doc_id: "d",
  });

  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
  });

  const ask = async (text: string) => {
    await userEvent.type(screen.getByLabelText("Your question"), text);
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
  };

  it("sends the server doc id and earlier turns so follow-ups keep context", async () => {
    const spy = vi.spyOn(api, "askQuestion").mockResolvedValueOnce(answer("First answer [p. 2]")).mockResolvedValueOnce(answer("Second"));
    render(<ChatWindow docId={"c".repeat(32)} onNewResponse={vi.fn()} />);

    await ask("first question");
    await screen.findByText(/First answer/);
    await ask("and what about page 6?");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));

    expect(spy.mock.calls[0][0]).toBe("first question");
    expect(spy.mock.calls[0][1]).toBe("c".repeat(32));
    expect(spy.mock.calls[0][2]).toEqual([]); // welcome message is not history
    expect(spy.mock.calls[1][2]).toEqual([
      { role: "user", content: "first question" },
      { role: "assistant", content: "First answer [p. 2]" },
    ]);
  });

  it("passes visuals up and shows cited pages", async () => {
    vi.spyOn(api, "askQuestion").mockResolvedValue({
      ...answer("Revenue grew."),
      supporting_visuals: [{ id: "v1", type: "image", page: 2, src: "/extracted/x/f.png", caption: "Fig 1" }],
    });
    const onNew = vi.fn();
    render(<ChatWindow docId="d" onNewResponse={onNew} />);
    await ask("revenue?");
    await screen.findByText("Page 2");
    expect(onNew).toHaveBeenCalledWith([expect.objectContaining({ id: "v1", src: "/extracted/x/f.png" })]);
  });

  it("shows the backend's error message and does not feed errors back as history", async () => {
    const spy = vi
      .spyOn(api, "askQuestion")
      .mockRejectedValueOnce(new api.ApiError("Document is still being processed.", 409))
      .mockResolvedValueOnce(answer("ok"));
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(<ChatWindow docId="d" onNewResponse={vi.fn()} />);

    await ask("q1");
    expect(await screen.findByRole("alert")).toHaveTextContent("still being processed");

    await ask("q2");
    await waitFor(() => expect(spy).toHaveBeenCalledTimes(2));
    expect(spy.mock.calls[1][2]).toEqual([{ role: "user", content: "q1" }]);
  });
});

describe("ErrorBoundary", () => {
  it("shows a recovery screen instead of a blank page", () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    const Boom = () => {
      throw new Error("render crash");
    };
    render(
      <MemoryRouter>
        <ErrorBoundary>
          <Boom />
        </ErrorBoundary>
      </MemoryRouter>,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Something went wrong");
  });
});
