from app.rag.code_index_builder import CodeIndexBuilder


def test_code_index_builder_indexes_real_source_and_skips_dependency_trees(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    source = workspace / "service.py"
    source.write_text(
        "def immutable_graph_patch():\n    return 'reference-first'\n",
        encoding="utf-8",
    )
    dependency = workspace / "node_modules"
    dependency.mkdir()
    (dependency / "ignored.ts").write_text("const immutable_graph_patch = true", encoding="utf-8")

    builder = CodeIndexBuilder(project_root=workspace, cache_dir=tmp_path / "index")
    result = builder.build_code_index(str(workspace), enable_vectors=False)
    hits = builder.search_code("immutable_graph_patch", 5, prefer_vectors=False)

    assert result["success"] is True
    assert result["indexed_files"] == 1
    assert hits
    assert hits[0]["metadata"]["file_path"] == "service.py"
    assert all("node_modules" not in hit["metadata"]["file_path"] for hit in hits)
