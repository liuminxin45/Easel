"""Compatibility CLI entry; all traffic uses the unified toolbox app."""
def run(store):
    import uvicorn
    from easel_workbench.runtime.toolbox_server import create_app
    uvicorn.run(create_app(store=store),host='127.0.0.1',port=9123,access_log=False)
