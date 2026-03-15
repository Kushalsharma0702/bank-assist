const fs = require("fs");
const file = "frontend/src/components/ConversationBot.jsx";
let content = fs.readFileSync(file, "utf8");

content = content.replace("const ws = new WebSocket(", "console.log('CONNECTING TO:', `${WS_BASE_URL}${wsPath}?${qs.toString()}`);\n      const ws = new WebSocket(");

fs.writeFileSync(file, content);
