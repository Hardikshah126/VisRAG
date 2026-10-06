import { motion } from "framer-motion";
import { User, Bot, FileText, AlertCircle } from "lucide-react";
import ReactMarkdown from "react-markdown";
import { cn } from "@/lib/utils";

export interface MessageSource {
  page: number;
  text: string;
}

export interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: MessageSource[];
  isError?: boolean;
  timestamp: Date;
}

interface MessageBubbleProps {
  message: Message;
}

export function MessageBubble({ message }: MessageBubbleProps) {
  const isUser = message.role === "user";

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.3 }}
      className={cn("flex gap-3 w-full", isUser ? "flex-row-reverse" : "flex-row")}
    >
      {/* Avatar */}
      <div
        className={cn(
          "flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center",
          isUser ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground",
        )}
      >
        {isUser ? <User className="w-4 h-4" /> : <Bot className="w-4 h-4" />}
      </div>

      {/* Message content */}
      <div className={cn("flex flex-col gap-2 max-w-[80%]", isUser ? "items-end" : "items-start")}>
        <div className={cn(isUser ? "chat-bubble-user" : "chat-bubble-assistant")}>
          {isUser ? (
            <p className="text-sm leading-relaxed whitespace-pre-wrap break-words">{message.content}</p>
          ) : message.isError ? (
            <p role="alert" className="flex items-start gap-2 text-sm leading-relaxed text-destructive">
              <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              {message.content}
            </p>
          ) : (
            // react-markdown does not render raw HTML, so model output cannot inject markup.
            <div className="prose prose-sm max-w-none break-words text-muted-foreground prose-headings:text-foreground prose-strong:text-foreground">
              <ReactMarkdown
                components={{
                  a: ({ node: _node, ...props }) => <a {...props} target="_blank" rel="noopener noreferrer" />,
                }}
              >
                {message.content}
              </ReactMarkdown>
            </div>
          )}
        </div>

        {/* Pages the answer cites */}
        {!isUser && message.sources && message.sources.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {message.sources.map((source, i) => (
              <motion.div
                key={source.page}
                initial={{ opacity: 0, scale: 0.9 }}
                animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: i * 0.1 }}
                className="flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-secondary text-xs text-muted-foreground"
              >
                <FileText className="w-3 h-3" />
                <span>Page {source.page}</span>
              </motion.div>
            ))}
          </div>
        )}

        <span className="text-xs text-muted-foreground">
          {message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
        </span>
      </div>
    </motion.div>
  );
}

export function TypingIndicator() {
  return (
    <motion.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} className="flex gap-3">
      <div className="flex-shrink-0 w-9 h-9 rounded-xl flex items-center justify-center bg-secondary text-muted-foreground">
        <Bot className="w-4 h-4" />
      </div>
      <div className="chat-bubble-assistant flex items-center gap-1.5 px-5" aria-label="Assistant is typing">
        <span className="typing-dot" />
        <span className="typing-dot" />
        <span className="typing-dot" />
      </div>
    </motion.div>
  );
}
