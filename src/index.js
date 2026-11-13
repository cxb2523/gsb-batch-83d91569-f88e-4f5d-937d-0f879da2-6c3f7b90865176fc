import { Server } from "@modelcontextprotocol/sdk/server/index.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { ListToolsRequestSchema, CallToolRequestSchema } from "@modelcontextprotocol/sdk/types.js";
import { createBridge } from "./bridge.js";

const server = new Server(
  { name: "hasdata-mcp-bridge", version: "1.0.0" },
  { capabilities: { tools: {} } }
);

const bridge = createBridge();

server.setRequestHandler(ListToolsRequestSchema, (request) => bridge.listTools(request));
server.setRequestHandler(CallToolRequestSchema, (request) => bridge.callTool(request));

const transport = new StdioServerTransport();
await server.connect(transport);
console.error("HasData Manual Bridge is online!");
