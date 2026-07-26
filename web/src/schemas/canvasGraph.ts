import { z } from "zod";

export const canvasNodeDataSchema = z.object({
  id: z.string(),
  agent_name: z.string(),
  description: z.string(),
  params: z.record(z.string(), z.unknown()),
});

export const canvasWireDataSchema = z.object({
  from_node: z.string(),
  to_node: z.string(),
  repeat_count: z.number(),
});

export const canvasGraphDataSchema = z.object({
  nodes: z.array(canvasNodeDataSchema),
  wires: z.array(canvasWireDataSchema),
});
