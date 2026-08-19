#!/usr/bin/env python3
"""
构建知识图谱脚本
从RAG文档构建知识图谱，按角色分类
"""
import sys
import os
from pathlib import Path

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from app.services.ragservice import RAGService
from app.services.knowledgegraphservice import knowledge_graph_service

# 角色ID映射
ROLE_MAPPING = {
    "lawyer": "律师",
    "teacher": "教师", 
    "programmer": "程序员",
    "writer": "作家"
}

def build_knowledge_graph_for_role(role_id: str):
    """为指定角色构建知识图谱"""
    print(f"开始为角色 {role_id} 构建知识图谱...")
    
    # 初始化RAG服务
    rag_service = RAGService()
    
    # 获取该角色的所有文档
    role_documents = []
    for doc_id, doc_data in rag_service.documents.items():
        if doc_data.get("role_id") == role_id:
            role_documents.append({
                "doc_id": doc_id,
                "text": doc_data.get("text", ""),
                "metadata": doc_data.get("metadata", {}),
                "role_id": role_id
            })
    
    if not role_documents:
        print(f"角色 {role_id} 没有文档，跳过构建")
        return
    
    print(f"找到 {len(role_documents)} 个文档")
    
    # 构建知识图谱
    knowledge_graph_service.build_from_documents(role_documents, role_id)
    
    # 获取统计信息
    kg = knowledge_graph_service.kg
    role_entities = [e for e in kg.entities.values() if e.get("properties", {}).get("role_id") == role_id]
    role_triples = []
    for triple in kg.triples:
        subject, relation, obj = triple
        subject_entity = kg.entities.get(subject, {})
        obj_entity = kg.entities.get(obj, {})
        if (subject_entity.get("properties", {}).get("role_id") == role_id and 
            obj_entity.get("properties", {}).get("role_id") == role_id):
            role_triples.append(triple)
    
    print(f"知识图谱构建完成:")
    print(f"  - 实体数: {len(role_entities)}")
    print(f"  - 三元组数: {len(role_triples)}")

def build_all_knowledge_graphs():
    """为所有角色构建知识图谱"""
    print("开始为所有角色构建知识图谱...")
    
    for role_id in ROLE_MAPPING.keys():
        build_knowledge_graph_for_role(role_id)
        print()
    
    # 获取总体统计
    kg = knowledge_graph_service.kg
    print(f"总体统计:")
    print(f"  - 总实体数: {len(kg.entities)}")
    print(f"  - 总三元组数: {len(kg.triples)}")
    print(f"  - 总关系数: {len(kg.relations)}")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description='构建知识图谱')
    parser.add_argument('--role', type=str, help='指定角色ID（lawyer/teacher/programmer/writer）')
    args = parser.parse_args()
    
    if args.role:
        build_knowledge_graph_for_role(args.role)
    else:
        build_all_knowledge_graphs()

