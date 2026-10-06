import { useState, useRef, useEffect } from "react";
import { motion } from "framer-motion";
import { Send, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MessageBubble, TypingIndicator, Message } from "./MessageBubble";

import { ApiError, askQuestion, type ChatTurn } from "@/lib/api";

interface ChatWindowProps {
  docId: string;
  onNewResponse: (visuals: VisualEvidence[]) => void;
}

/* Visual evidence shown in the side panel */
export interface VisualEvidence {
  id: string;
  type: "image" | "table";
  src?: string;
  caption?: string;
  page: number;
  tableData?: string[][];
}

/** How many earlier messages the backend gets for follow-up questions. */
const HISTORY_TURNS = 10;
const MAX_TURN_CHARS = 4000; // backend limit per turn

const WELCOME: Message = {
  id: "welcome",
  role: "assistant",
  content: `### Welcome to VisRAG!

Ask me anything about your PDF and I will answer with supporting images and tables.`,
  timestamp: new Date(),
};

export function ChatWindow({ docId, onNewResponse }: ChatWindowProps) {
  const [messages, setMessages] = useState<Message[]>([WELCOME]);
  const [input, setInput] = useState("");
  const [isTyping, setIsTyping] = useState(false);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const nextId = useRef(0);
  const newId = () => `m${nextId.current++}`;

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isTyping]);

  const buildHistory = (): ChatTurn[] =>
    messages
      .filter((m) => m.id !== WELCOME.id && !m.isError)
      .slice(-HISTORY_TURNS)
      .map((m) => ({ role: m.role, content: m.content.slice(0, MAX_TURN_CHARS) }));

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isTyping) return;

    const question = input.trim();
    const history = buildHistory();

    setMessages((prev) => [...prev, { id: newId(), role: "user", content: question, timestamp: new Date() }]);
    setInput("");
    setIsTyping(true);

    try {
      const res = await askQuestion(question, docId, history);

      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          content: res.answer || "The model returned an empty answer.",
          sources: res.citations?.map((page) => ({ page, text: "" })),
          timestamp: new Date(),
        },
      ]);

      onNewResponse(
        (res.supporting_visuals ?? []).map((v) => ({
          id: v.id,
          type: v.type,
          src: v.src ?? undefined, // relative; VisualPanel resolves it against the API origin
          caption: v.caption ?? undefined,
          page: v.page,
          tableData: v.tableData ?? undefined,
        })),
      );
    } catch (err) {
      console.error("Ask error:", err);
      setMessages((prev) => [
        ...prev,
        {
          id: newId(),
          role: "assistant",
          isError: true,
          content: err instanceof ApiError ? err.message : "Something went wrong while answering.",
          timestamp: new Date(),
        },
      ]);
    } finally {
      setIsTyping(false);
    }
  };

  return (
    <div className="flex flex-col h-full">
      <div className="flex-1 overflow-y-auto custom-scrollbar p-6 space-y-6" aria-live="polite">
        {messages.map((message) => (
          <MessageBubble key={message.id} message={message} />
        ))}

        {isTyping && <TypingIndicator />}
        <div ref={messagesEndRef} />
      </div>

      <div className="border-t bg-background p-4">
        <form onSubmit={handleSubmit} className="flex gap-3">
          <div className="relative flex-1">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Ask about your document..."
              aria-label="Your question"
              maxLength={2000}
              className="w-full px-4 py-3 pr-12 rounded-xl border bg-card"
              disabled={isTyping}
            />
            <div className="absolute right-3 top-1/2 -translate-y-1/2">
              <Sparkles className="w-4 h-4 text-muted-foreground" />
            </div>
          </div>

          <motion.div whileHover={{ scale: 1.02 }} whileTap={{ scale: 0.98 }}>
            <Button
              type="submit"
              aria-label="Send"
              disabled={!input.trim() || isTyping}
              className="h-12 px-6 rounded-xl bg-primary"
            >
              <Send className="w-4 h-4" />
            </Button>
          </motion.div>
        </form>
      </div>
    </div>
  );
}
