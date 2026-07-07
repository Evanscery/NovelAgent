/**
 * AgentNode — a single react-flow node rendering Name + Task.
 * Used by WorkflowCanvasView (todo 27). Per guide:356-360 nodes show
 * agent identity + task; clicking opens the side panel (handled by the
 * view via onNodeClick).
 */

import { memo, useCallback } from "react";
import { Handle, Position, type NodeProps } from "@xyflow/react";

export interface AgentNodePayload extends Record<string, unknown> {
  agentName: string;
  description: string;
}

function AgentNodeComponent({ data, selected }: NodeProps): React.ReactNode {
  const payload = data as AgentNodePayload;
  const stop = useCallback((e: React.MouseEvent) => {
    // Prevent the canvas drag-from-handle when clicking the body.
    e.stopPropagation();
  }, []);
  return (
    <div
      className={`agent-node${selected ? " agent-node--selected" : ""}`}
      onClick={stop}
      role="button"
      tabIndex={0}
    >
      <Handle type="target" position={Position.Top} />
      <div className="agent-node__head">{payload.agentName}</div>
      <div className="agent-node__task">{payload.description}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  );
}

export const AgentNode = memo(AgentNodeComponent);
export default AgentNode;
