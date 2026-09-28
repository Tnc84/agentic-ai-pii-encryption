try:
    from langgraph.checkpoint.sqlite import SqliteSaver

    print("ok", SqliteSaver)
    print("from_conn", hasattr(SqliteSaver, "from_conn_string"))
except Exception as exc:
    print("err", type(exc), exc)
