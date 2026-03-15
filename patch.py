with open(r'backend\routers\duplex_router.py', 'r', encoding='utf-8') as f:
    text = f.read()

text = text.replace('logger.error(f\"\U0001f4a5 Fatal: {exc}\", exc_info=True)', 'logger.error(f\"\U0001f4a5 Fatal: {exc}\", exc_info=True); open(\"crash_log.txt\",\"a\").write(str(type(exc)) + str(exc) + str(exc.__traceback__.tb_frame) + \"\\n\")')

if 'crash_log' not in text:
    print('Replace failed')
    text = text.replace('logger.error(f', 'open(\"crash_log.txt\", \"a\").write(str(type(exc)) + str(exc) + \"\\\\n\"); logger.error(f')

with open(r'backend\routers\duplex_router.py', 'w', encoding='utf-8') as f:
    f.write(text)
