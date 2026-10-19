// An approval question from Symphony's stdio protocol. A click answers the
// question with the chosen choice through the answer frame; it never sends a
// chat message.
import { Button } from "@/components/ui/button";
import type { InputRequestedFrame } from "./frames";

export function ApprovalCard({
  question,
  onAnswer,
}: {
  question: InputRequestedFrame;
  onAnswer: (value: string) => void;
}) {
  const choices = question.choices || [];
  const detail = question.detail || question.question;
  return (
    <section className="approval-card" aria-label="Approval required">
      <p className="approval-detail">{detail}</p>
      {(question.target || typeof question.bytes === "number") && (
        <p className="approval-meta">
          {question.target && <code>{question.target}</code>}
          {typeof question.bytes === "number" && (
            <span>{question.bytes.toLocaleString()} bytes</span>
          )}
        </p>
      )}
      <div className="approval-choices">
        {choices.map((choice) => (
          <Button
            key={choice}
            variant={choice === question.default ? "default" : "outline"}
            size="sm"
            autoFocus={choice === question.default}
            onClick={() => onAnswer(choice)}
          >
            {choice}
          </Button>
        ))}
      </div>
    </section>
  );
}
