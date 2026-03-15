const fs = require("fs");
const file = "frontend/src/components/ConversationBot.jsx";
let content = fs.readFileSync(file, "utf8");

content = content.replace("ws.onopen = () => {", "ws.onopen = () => {\n        console.log('WS OPENED!');");
content = content.replace("ws.onmessage = handleWsMessage;", "ws.onmessage = (e) => {\n        console.log('WS MSG:', e.data);\n        handleWsMessage(e);\n      };");

fs.writeFileSync(file, content);
