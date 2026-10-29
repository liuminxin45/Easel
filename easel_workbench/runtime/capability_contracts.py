"""Read an execution contract from the actual frozen, versioned skill resource."""
def resource_text(snapshot, name):
    suffix = '/references/' + name
    resources = [resource for skill in snapshot.get('skills', [])
                 for resource in skill.get('resources', [])
                 if resource.get('path', '').endswith(suffix)]
    if len(resources) != 1:
        raise ValueError('技能版本缺少唯一执行合同：' + name)
    item = resources[0]
    content = item.get('content')
    if not item.get('available') or not isinstance(content, str):
        raise ValueError('技能执行合同原件不可用：' + name)
    # Blob bytes are verified by the registry; UTF-8 content may have a BOM
    # removed for reading, so do not claim its re-encoding is the original SHA.
    return content
