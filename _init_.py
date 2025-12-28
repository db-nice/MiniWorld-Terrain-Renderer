import bpy
import os
import re
import math
import shutil
from mathutils import Vector, Matrix
from collections import defaultdict
import traceback

bl_info = {
    "name": "方块网格生成器增强版",
    "author": "MiniMax Agent",
    "version": (3, 14, 0),  # 版本更新：修复映射表重新加载问题
    "blender": (3, 0, 0),
    "location": "3D视图 > 侧边栏 > 方块工具",
    "description": "从文件夹加载OBJ方块模型，支持映射表驱动的主模型+子模型系统，支持自发光贴图，修复尺寸缩放问题和映射表重新加载",
    "category": "Object",
}

# ============================================================================
# 全局管理类
# ============================================================================

_block_model_manager_instance = None

class BlockModelManager:
    """方块模型管理器"""
    
    def __new__(cls):
        global _block_model_manager_instance
        if _block_model_manager_instance is None:
            _block_model_manager_instance = super(BlockModelManager, cls).__new__(cls)
            _block_model_manager_instance._initialized = False
        return _block_model_manager_instance
    
    def __init__(self):
        if not self._initialized:
            self._templates = {}  # position_id -> template_object
            self._model_configs = {}  # position_id -> ModelConfig
            self._mapping_table = None
            self._mapping_file_path = None
            self._materials = {}  # 材质缓存
            self._loaded_textures = {}  # 已加载的贴图缓存
            self._initialized = True
    
    def get_template(self, position_id):
        """获取位置ID对应的模板"""
        return self._templates.get(position_id)
    
    def set_template(self, position_id, template_obj):
        """设置位置ID对应的模板"""
        self._templates[position_id] = template_obj
    
    def has_template_for_id(self, position_id):
        """检查是否有指定位置ID的模板"""
        return position_id in self._templates
    
    def get_mapping_for_id(self, position_id):
        """获取指定位置ID的映射数据"""
        if self._mapping_table:
            return self._mapping_table.get(position_id)
        return None
    
    def get_mapping_count(self):
        """获取映射表条目数量"""
        if self._mapping_table:
            return len(self._mapping_table)
        return 0
    
    def set_mapping_table(self, mapping_file_path):
        """设置映射表"""
        print(f"设置映射表路径: {mapping_file_path}")
        self._mapping_file_path = mapping_file_path
        self._mapping_table = parse_mapping_table(mapping_file_path)
        print(f"映射表已加载，共 {len(self._mapping_table)} 个条目")
    
    def get_model_config(self, position_id):
        """获取指定位置ID的模型配置"""
        return self._model_configs.get(position_id)
    
    def set_model_config(self, position_id, model_config):
        """设置指定位置ID的模型配置"""
        self._model_configs[position_id] = model_config
    
    def get_material(self, material_name):
        """获取材质"""
        return self._materials.get(material_name)
    
    def set_material(self, material_name, material):
        """设置材质"""
        self._materials[material_name] = material
    
    def clear_templates_and_configs(self):
        """清除模板和模型配置，但保留映射表和材质缓存"""
        print("清除模板和模型配置...")
        
        # 清除模板引用
        self._templates.clear()
        self._model_configs.clear()
        
        print(f"模板和模型配置已清除")
    
    def clear_all_except_mapping(self):
        """清除除映射表外的所有数据"""
        print("清除除映射表外的所有数据...")
        
        self._templates.clear()
        self._model_configs.clear()
        self._materials.clear()
        self._loaded_textures.clear()
        
        print(f"除映射表外的所有数据已清除")
    
    def clear_all(self):
        """清除所有数据（包括映射表）"""
        print("清除所有数据...")
        
        self._templates.clear()
        self._model_configs.clear()
        self._materials.clear()
        self._loaded_textures.clear()
        self._mapping_table = None
        self._mapping_file_path = None
        
        print(f"所有数据已清除")
    
    def clear_duplicate_materials(self):
        """清理重复的材质"""
        print("清理重复材质...")
        
        # 查找所有以BlockMat_开头的材质
        block_materials = {}
        duplicates = []
        
        for mat in bpy.data.materials:
            if mat.name.startswith("BlockMat_"):
                base_name = re.sub(r'\.\d{3}$', '', mat.name)  # 移除.001等后缀
                
                if base_name not in block_materials:
                    block_materials[base_name] = [mat]
                else:
                    block_materials[base_name].append(mat)
        
        # 标记需要清理的重复材质
        for base_name, mats in block_materials.items():
            if len(mats) > 1:
                # 保留第一个，标记其他的为重复
                for i, mat in enumerate(mats):
                    if i == 0:
                        print(f"保留材质: {mat.name} (原始: {base_name})")
                    else:
                        duplicates.append(mat)
                        print(f"标记为重复: {mat.name}")
        
        # 从管理器中移除重复材质
        for mat in duplicates:
            for key in list(self._materials.keys()):
                if self._materials[key] == mat:
                    del self._materials[key]
                    print(f"从管理器中移除: {key}")
        
        print(f"找到 {len(duplicates)} 个重复材质")
        return duplicates
    
    def reload_mapping_table(self, scene):
        """重新加载映射表（如果路径存在）"""
        if scene.mapping_table_path and os.path.exists(scene.mapping_table_path):
            print(f"重新加载映射表: {scene.mapping_table_path}")
            self.set_mapping_table(scene.mapping_table_path)
            return True
        else:
            print(f"无法重新加载映射表: 路径不存在或未设置")
            return False
    
    def get_unique_material_name(self, base_name):
        """获取唯一的材质名称"""
        if base_name not in bpy.data.materials:
            return base_name
        
        counter = 1
        while f"{base_name}.{str(counter).zfill(3)}" in bpy.data.materials:
            counter += 1
        
        return f"{base_name}.{str(counter).zfill(3)}"

class ModelConfig:
    """模型配置信息"""
    def __init__(self, position_id, mapping_data, texture_base_path, models_base_path):
        self.position_id = position_id
        self.mapping_data = mapping_data
        self.texture_base_path = texture_base_path
        self.models_base_path = models_base_path
        
        print(f"\n模型配置创建 - ID: {position_id}")
        
        # 从映射数据中获取信息
        if mapping_data:
            self.blocktype = mapping_data.get('blocktype', '')
            self.main_texture_prefix = mapping_data.get('main_texture_prefix', '')
            self.submodel_name = mapping_data.get('submodel_name', '')
            self.z_texture_prefix = mapping_data.get('z_texture_prefix', '')
            
            print(f"  Blocktype: {self.blocktype}")
            print(f"  主贴图前缀: {self.main_texture_prefix}")
            print(f"  子模型名称: {self.submodel_name}")
            print(f"  Z面贴图前缀: {self.z_texture_prefix}")
        else:
            # 如果没有映射数据，使用空值
            self.blocktype = ''
            self.main_texture_prefix = ''
            self.submodel_name = ''
            self.z_texture_prefix = ''
            print(f"  警告：没有找到位置ID {position_id} 的映射数据")
        
        # 确定材质系统类型 - 修改：teamspawn类型使用独立材质系统
        if self.blocktype == 'teamspawn':
            # teamspawn类型：只使用一个材质球，贴图处理模型和正常数组相反
            self.material_system = 'teamspawn_system'
        elif self.blocktype in ['soil', 'plantash']:
            # soil类型：Z面特殊，其他面使用主贴图
            self.material_system = 'soil_system'
        elif self.blocktype in ['minestone', 'stone', 'buildblueprint', 'regionreplicator', 'replicator', 'airwall', 'copier']:
            # minestone类型：X、Y、Z面独立调配，每个面使用自己的贴图
            self.material_system = 'minestone_system'
        elif self.blocktype in ['replicator','regionreplicator','airwall', 'copier']:
            # 检查是否有主贴图前缀
            if self.main_texture_prefix:
                # 有主贴图前缀，使用统一材质系统
                self.material_system = 'minestone_system'  # 使用minestone系统，独立调配
            else:
                # 没有主贴图前缀，只创建子模型
                self.material_system = 'submodel_only'
        else:
            self.material_system = 'default_system'
        
        print(f"  材质系统: {self.material_system}")
        
        # 确定主模型和子模型路径
        if self.blocktype == 'teamspawn':
            # teamspawn类型使用id/teamspawn作为主模型
            self.main_model_path = os.path.join(models_base_path, str(position_id), "teamspawn.obj")
            print(f"  teamspawn类型：主模型路径设置为 {self.main_model_path}")
            
            # teamspawn类型强制使用主模型，不使用子模型
            self.submodel_name = ''  # 清空子模型名称
            self.submodel_path = None
            print(f"  teamspawn类型：强制使用主模型，不使用子模型")
        else:
            # 其他类型使用models/block.obj作为主模型
            self.main_model_path = os.path.join(models_base_path, "models", "block.obj")
            print(f"  普通类型：主模型路径设置为 {self.main_model_path}")
        
        self.submodel_path = None
        
        # 根据映射数据决定是否需要主模型
        self.need_main_model = True
        
        # 清晰的逻辑判断
        if self.submodel_name:
            # 有子模型名称，检查是否需要主模型
            if not self.main_texture_prefix:
                self.need_main_model = False
                print(f"  不需要主模型：有子模型但主贴图前缀为空")
            else:
                self.need_main_model = True
                print(f"  需要主模型：有子模型且有主贴图前缀 {self.main_texture_prefix}")
        else:
            # 没有子模型名称，检查是否需要主模型
            if self.main_texture_prefix:
                self.need_main_model = True
                print(f"  需要主模型：有主贴图前缀 {self.main_texture_prefix}")
            else:
                self.need_main_model = False
                print(f"  不需要主模型：没有子模型且没有主贴图前缀")
        
        # 特殊处理：对于只创建子模型的类型，强制设置need_main_model=False
        if self.material_system == 'submodel_only':
            self.need_main_model = False
            print(f"  强制不需要主模型：{self.blocktype}类型只创建子模型")
        
        # 特殊处理：teamspawn类型强制使用主模型，不使用子模型
        if self.blocktype == 'teamspawn':
            self.need_main_model = True
            self.submodel_name = ''  # 清空子模型名称
            self.submodel_path = None
            print(f"  特殊处理：teamspawn类型强制使用主模型，使用id/teamspawn.obj")
        
        # 查找子模型路径
        if self.submodel_name and self.blocktype != 'teamspawn':  # teamspawn类型跳过子模型查找
            # 尝试在id文件夹中查找子模型
            id_folder = os.path.join(models_base_path, str(position_id))
            submodel_name = self.submodel_name
            
            # 查找子模型文件
            possible_names = [
                f"{submodel_name}.obj",
                f"{submodel_name}_lod1.obj",
                f"{submodel_name}_lod0.obj",
            ]
            
            for name in possible_names:
                path = os.path.join(id_folder, name)
                if os.path.exists(path):
                    self.submodel_path = path
                    print(f"  找到子模型文件: {path}")
                    break
            
            # 如果没找到，尝试在models文件夹中查找
            if not self.submodel_path:
                for name in possible_names:
                    path = os.path.join(models_base_path, "models", name)
                    if os.path.exists(path):
                        self.submodel_path = path
                        print(f"  在models文件夹找到子模型文件: {path}")
                        break
            
            if not self.submodel_path:
                print(f"  警告：未找到子模型文件 {submodel_name}.obj")
        else:
            print(f"  无子模型名称，跳过子模型查找")
    
    def has_main_model(self):
        """是否需要主模型"""
        # 对于teamspawn类型，检查id/teamspawn.obj是否存在
        if self.blocktype == 'teamspawn':
            return self.need_main_model and os.path.exists(self.main_model_path)
        else:
            return self.need_main_model and os.path.exists(self.main_model_path)
    
    def has_submodel(self):
        """是否需要子模型"""
        # teamspawn类型不需要子模型
        if self.blocktype == 'teamspawn':
            return False
        return self.submodel_path and os.path.exists(self.submodel_path)
    
    def get_texture_path(self, face_type='x'):
        """获取贴图路径 - 根据材质系统决定使用哪种UV系统"""
        if not self.main_texture_prefix:
            return None
        
        # 根据材质系统判断使用哪种材质系统
        if self.material_system == 'teamspawn_system':
            # teamspawn类型：只使用一个材质球，贴图处理模型和正常数组相反
            return self._get_teamspawn_texture_path()
        elif self.material_system == 'soil_system':
            # soil/plantash类型：Z面使用特殊贴图，其他面使用主贴图
            return self._get_soil_texture_path(face_type)
        elif self.material_system == 'minestone_system':
            # minestone类型：X、Y、Z面独立调配，每个面使用自己的贴图
            return self._get_minestone_texture_path(face_type)
        elif self.material_system == 'submodel_only':
            # replicator/airwall类型：只创建子模型，不需要主模型贴图
            return None
        else:
            # 默认：标准XYZ面贴图
            return self._get_default_texture_path(face_type)
    
    def _get_default_texture_path(self, face_type='x'):
        """默认贴图路径（标准XYZ面）"""
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        
        # 标准硬链接文件名规则
        if face_type.lower() == 'x':
            expected_filename = f"{self.main_texture_prefix}_z.png"
        elif face_type.lower() == 'y':
            expected_filename = f"{self.main_texture_prefix}_x.png"
        elif face_type.lower() == 'z':
            expected_filename = f"{self.main_texture_prefix}_y.png"
        else:
            expected_filename = f"{self.main_texture_prefix}_{face_type}.png"
        
        # 构建完整路径
        path = os.path.join(id_folder, expected_filename)
        if os.path.exists(path):
            return path
        
        return None
    
    def _get_minestone_texture_path(self, face_type='x'):
        """minestone类型贴图路径（X、Y、Z面独立，每个面使用自己的贴图）"""
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        
        # minestone类型各面独立，根据face_type使用不同的贴图
        if face_type.lower() == 'x':
            # X面贴图
            expected_filename = f"{self.main_texture_prefix}_z.png"
        elif face_type.lower() == 'y':
            # Y面贴图
            expected_filename = f"{self.main_texture_prefix}_x.png"
        elif face_type.lower() == 'z':
            # Z面贴图
            expected_filename = f"{self.main_texture_prefix}_y.png"
        else:
            # 其他面使用默认贴图
            expected_filename = f"{self.main_texture_prefix}.png"
        
        path = os.path.join(id_folder, expected_filename)
        
        if os.path.exists(path):
            return path
        
        # 如果没找到特定贴图，尝试使用主贴图作为后备
        fallback_path = os.path.join(id_folder, f"{self.main_texture_prefix}.png")
        if os.path.exists(fallback_path):
            return fallback_path
        
        return None
    
    def _get_soil_texture_path(self, face_type='x'):
        """soil类型贴图路径（Z面特殊，其他面使用主贴图）"""
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        
        print(f"  查找{face_type}面贴图 - ID: {self.position_id}, 主贴图前缀: {self.main_texture_prefix}, Z面贴图前缀: {self.z_texture_prefix}")
        
        if face_type.lower() == 'z':
            # Z面使用特殊贴图（如果有的话）
            if self.z_texture_prefix:
                expected_filename = f"{self.z_texture_prefix}.png"
                path = os.path.join(id_folder, expected_filename)
                if os.path.exists(path):
                    print(f"    ✓ 找到Z面特殊贴图: {expected_filename}")
                    return path
                else:
                    print(f"    ✗ Z面特殊贴图不存在: {path}")
            
            # 如果没有特殊Z面贴图，尝试其他命名
            possible_names = [
                f"{self.main_texture_prefix}_y.png",  # 标准Z面命名
                f"{self.main_texture_prefix}.png",    # 主贴图
                f"{self.main_texture_prefix}_z.png",  # 可能误标
                "blocks.grass.png",  # 尝试默认草地贴图
                "blockd.grass.png",  # 尝试默认草地贴图
            ]
            
            for name in possible_names:
                path = os.path.join(id_folder, name)
                if os.path.exists(path):
                    print(f"    ✓ 找到Z面替代贴图: {name}")
                    return path
            
            print(f"    ✗ 未找到Z面贴图")
        else:
            # X、-X、Y、-Y、-Z面使用主贴图
            expected_filename = f"{self.main_texture_prefix}.png"
            path = os.path.join(id_folder, expected_filename)
            if os.path.exists(path):
                print(f"    ✓ 找到{face_type}面主贴图: {expected_filename}")
                return path
            
            # 尝试其他可能的命名
            other_names = [
                f"{self.main_texture_prefix}_x.png",
                f"{self.main_texture_prefix}_y.png",
                "blocks.grass.png",
                "blockd.grass.png",
            ]
            
            for name in other_names:
                path = os.path.join(id_folder, name)
                if os.path.exists(path):
                    print(f"    ✓ 找到{face_type}面替代贴图: {name}")
                    return path
            
            print(f"    ✗ 未找到{face_type}面贴图")
        
        return None
    
    def _get_teamspawn_texture_path(self):
        """teamspawn类型贴图路径（只使用一个贴图，贴图处理模型和正常数组相反）"""
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        
        print(f"  查找teamspawn贴图 - ID: {self.position_id}, 主贴图前缀: {self.main_texture_prefix}")
        
        # teamspawn类型只需要一个贴图，使用主贴图前缀
        expected_filename = f"{self.main_texture_prefix}.png"
        path = os.path.join(id_folder, expected_filename)
        
        if os.path.exists(path):
            print(f"    ✓ 找到teamspawn贴图: {expected_filename}")
            return path
        
        # 如果没找到，尝试其他可能的命名
        possible_names = [
            f"{self.main_texture_prefix}_x.png",
            f"{self.main_texture_prefix}_y.png",
            f"{self.main_texture_prefix}_z.png",
            "teamspawn.png",
            "teamspawn0.png",
        ]
        
        for name in possible_names:
            path = os.path.join(id_folder, name)
            if os.path.exists(path):
                print(f"    ✓ 找到teamspawn替代贴图: {name}")
                return path
        
        print(f"    ✗ 未找到teamspawn贴图")
        return None
    
    def get_submodel_texture_path(self):
        """获取子模型漫反射贴图路径"""
        if not self.submodel_name or self.blocktype == 'teamspawn':  # teamspawn类型没有子模型
            return None
        
        # 检查多个可能的路径
        possible_paths = []
        
        # 1. 在id文件夹中查找
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}.png"))
        
        # 2. 在texture_base_path根目录下查找
        possible_paths.append(os.path.join(self.texture_base_path, f"{self.submodel_name}.png"))
        
        # 3. 在models文件夹中查找
        models_folder = os.path.join(self.models_base_path, "models")
        possible_paths.append(os.path.join(models_folder, f"{self.submodel_name}.png"))
        
        # 4. 在id文件夹中的models子文件夹中查找
        possible_paths.append(os.path.join(id_folder, "models", f"{self.submodel_name}.png"))
        
        for path in possible_paths:
            if os.path.exists(path):
                print(f"✓ 找到子模型漫反射贴图: {path}")
                return path
        
        print(f"✗ 未找到子模型漫反射贴图: {self.submodel_name}.png")
        return None
    
    def get_submodel_emission_texture_path(self):
        """获取子模型自发光贴图路径"""
        if not self.submodel_name or self.blocktype == 'teamspawn':  # teamspawn类型没有子模型
            return None
        
        # 检查多个可能的路径
        possible_paths = []
        
        # 1. 在id文件夹中查找
        id_folder = os.path.join(self.texture_base_path, str(self.position_id))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}_emi.png"))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}_emission.png"))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}_emit.png"))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}_light.png"))
        possible_paths.append(os.path.join(id_folder, f"{self.submodel_name}_glow.png"))
        
        # 2. 在texture_base_path根目录下查找
        possible_paths.append(os.path.join(self.texture_base_path, f"{self.submodel_name}_emi.png"))
        
        # 3. 在models文件夹中查找
        models_folder = os.path.join(self.models_base_path, "models")
        possible_paths.append(os.path.join(models_folder, f"{self.submodel_name}_emi.png"))
        
        # 4. 在id文件夹中的models子文件夹中查找
        possible_paths.append(os.path.join(id_folder, "models", f"{self.submodel_name}_emi.png"))
        
        for path in possible_paths:
            if os.path.exists(path):
                print(f"✓ 找到子模型自发光贴图: {path}")
                return path
        
        print(f"✗ 未找到子模型自发光贴图: {self.submodel_name}_emi.png")
        return None

# ============================================================================
# 坐标解析函数
# ============================================================================

def parse_coordinate_string(coord_str):
    """解析坐标字符串，支持多种格式 - 支持新格式: x,y,z,id"""
    coordinates = []
    
    lines = coord_str.strip().split('\n')
    
    for line_num, line in enumerate(lines):
        line = line.strip()
        
        if not line or line.startswith('#'):
            continue
        
        try:
            # 支持新格式: x,y,z,id
            if ',' in line:
                parts = [p.strip() for p in line.split(',')]
                
                if len(parts) == 4:
                    # 新格式: x,y,z,id
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2])
                    block_id = int(parts[3])  # 新格式中id在最后
                    coordinates.append({
                        'id': block_id,
                        'x': int(round(x)),
                        'y': int(round(y)),
                        'z': int(round(z))
                    })
                elif len(parts) == 3:
                    # 格式: x,y,z (默认id为0)
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2])
                    coordinates.append({
                        'id': 0,
                        'x': int(round(x)),
                        'y': int(round(y)),
                        'z': int(round(z))
                    })
                else:
                    print(f"跳过无效行（字段数不正确）: {line}")
            
            # 支持空格分隔
            elif ' ' in line:
                parts = re.split(r'\s+', line.strip())
                if len(parts) == 4:
                    # 新格式: x y z id
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2])
                    block_id = int(parts[3])  # 新格式中id在最后
                    coordinates.append({
                        'id': block_id,
                        'x': int(round(x)),
                        'y': int(round(y)),
                        'z': int(round(z))
                    })
                elif len(parts) == 3:
                    x = float(parts[0])
                    y = float(parts[1])
                    z = float(parts[2])
                    coordinates.append({
                        'id': 0,
                        'x': int(round(x)),
                        'y': int(round(y)),
                        'z': int(round(z))
                    })
                else:
                    print(f"跳过无效行（字段数不正确）: {line}")
                    
        except (ValueError, IndexError) as e:
            print(f"第 {line_num + 1} 行解析错误: {line} - {str(e)}")
            continue
    
    print(f"坐标解析完成，共解析 {len(coordinates)} 个坐标")
    return coordinates

# ============================================================================
# 映射表解析函数
# ============================================================================

def parse_mapping_table(mapping_file_path):
    """解析映射表文件 - 兼容新格式"""
    mapping = {}
    
    if not os.path.exists(mapping_file_path):
        print(f"映射表文件不存在: {mapping_file_path}")
        return mapping
    
    try:
        with open(mapping_file_path, 'r', encoding='utf-8') as f:
            lines = f.readlines()
        
        valid_lines = 0
        invalid_lines = 0
        
        for line_num, line in enumerate(lines):
            line = line.strip()
            if not line or line.startswith('='):
                continue
            
            parts = line.split(',')
            if len(parts) < 46:  # 确保有足够的字段
                print(f"跳过无效行（字段不足）行 {line_num+1}: {line}")
                invalid_lines += 1
                continue
            
            try:
                position_id = int(parts[0])
                blocktype = parts[6] if len(parts) > 6 else ''           # 第7个字段（索引6）
                main_texture_prefix = parts[43] if len(parts) > 43 else ''  # 第44个字段（索引43）
                submodel_name = parts[44] if len(parts) > 44 else ''       # 第45个字段（索引44）
                z_texture_prefix = parts[44] if len(parts) > 44 else ''    # 第45个字段（索引44）
                
                # 特殊处理：如果第46个字段包含多个值，可能是"hupo,hupo1"格式
                if ',' in main_texture_prefix:
                    # 分割成主贴图前缀和Z面贴图前缀
                    split_parts = main_texture_prefix.split(',')
                    main_texture_prefix = split_parts[0] if len(split_parts) > 0 else ''
                    if len(split_parts) > 1:
                        z_texture_prefix = split_parts[1]
                
                mapping[position_id] = {
                    'position_id': position_id,
                    'blocktype': blocktype,
                    'main_texture_prefix': main_texture_prefix,
                    'submodel_name': submodel_name,
                    'z_texture_prefix': z_texture_prefix,
                    'has_main_texture': main_texture_prefix != '',
                    'has_submodel': submodel_name != '',
                    'has_z_texture': z_texture_prefix != '',
                    'all_parts': parts  # 保留所有字段
                }
                
                valid_lines += 1
                
                print(f"解析映射行 {line_num+1}: ID={position_id}, Blocktype={blocktype}, "
                      f"主贴图={main_texture_prefix}, 子模型={submodel_name}, Z面贴图={z_texture_prefix}")
                
            except (ValueError, IndexError) as e:
                print(f"解析行时出错 {line_num+1}: {line} - {e}")
                invalid_lines += 1
                continue
                
        print(f"映射表解析完成: 有效行={valid_lines}, 无效行={invalid_lines}, 总条目={len(mapping)}")
                
    except Exception as e:
        print(f"解析映射表文件失败: {e}")
        traceback.print_exc()
    
    return mapping

# ============================================================================
# 几何计算函数
# ============================================================================

def calculate_scaling_factor(original_size, scale_mode, custom_scale_factor=1.0, base_block_size=1.0):
    """根据缩放模式计算缩放因子"""
    print(f"计算缩放因子: 原始尺寸={original_size:.6f}, 缩放模式={scale_mode}, 基础网格大小={base_block_size}")
    
    if scale_mode == 'ONE_METER':
        # 缩放到基础网格大小（通常是1米）
        if original_size > 0.001:
            factor = base_block_size / original_size
            print(f"  ONE_METER模式缩放因子: {factor:.6f}")
            return factor
        else:
            print(f"  ONE_METER模式: 原始尺寸过小，使用默认因子1.0")
            return 1.0
    elif scale_mode == 'CUSTOM':
        # 使用自定义缩放因子
        print(f"  CUSTOM模式缩放因子: {custom_scale_factor:.6f}")
        return custom_scale_factor
    else:  # 'ORIGINAL'
        # 保持原始比例
        print(f"  ORIGINAL模式缩放因子: 1.0")
        return 1.0

def get_rotation_for_direction(direction_mode):
    """根据方向模式获取旋转角度（弧度）"""
    if direction_mode == 'EAST':
        return 0.0  # 朝向东方，不旋转
    elif direction_mode == 'SOUTH':
        return math.pi / 2  # 朝向南方，旋转90度
    elif direction_mode == 'WEST':
        return math.pi  # 朝向西方，旋转180度
    elif direction_mode == 'NORTH':
        return 3 * math.pi / 2  # 朝向北方，旋转270度
    else:
        return 0.0

def get_direction_vector(direction_mode):
    """根据方向模式获取方向向量"""
    if direction_mode == 'EAST':
        return Vector((1.0, 0.0, 0.0))
    elif direction_mode == 'SOUTH':
        return Vector((0.0, -1.0, 0.0))
    elif direction_mode == 'WEST':
        return Vector((-1.0, 0.0, 0.0))
    elif direction_mode == 'NORTH':
        return Vector((0.0, 1.0, 0.0))
    else:
        return Vector((1.0, 0.0, 0.0))

def calculate_model_dimensions(obj):
    """计算模型的尺寸"""
    if obj.type != 'MESH':
        return 0.0, 0.0, 0.0, 0.0
    
    # 获取世界坐标系下的边界框
    bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    x_coords = [corner.x for corner in bbox_corners]
    y_coords = [corner.y for corner in bbox_corners]
    z_coords = [corner.z for corner in bbox_corners]
    
    size_x = max(x_coords) - min(x_coords)
    size_y = max(y_coords) - min(y_coords)
    size_z = max(z_coords) - min(z_coords)
    max_size = max(size_x, size_y, size_z)
    
    return size_x, size_y, size_z, max_size

def calculate_model_center(obj):
    """计算模型的中心点"""
    if obj.type != 'MESH':
        return Vector((0, 0, 0))
    
    # 获取世界坐标系下的边界框
    bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
    x_coords = [corner.x for corner in bbox_corners]
    y_coords = [corner.y for corner in bbox_corners]
    z_coords = [corner.z for corner in bbox_corners]
    
    center_x = (min(x_coords) + max(x_coords)) / 2
    center_y = (min(y_coords) + max(y_coords)) / 2
    center_z = (min(z_coords) + max(z_coords)) / 2
    
    return Vector((center_x, center_y, center_z))

def get_world_coordinate_for_model(grid_coord, base_block_size, model_size_x, model_size_y, model_size_z, 
                                   direction_mode='EAST', use_model_center=False, adjacent_mode=True):
    """
    根据网格坐标和模型尺寸计算世界坐标
    """
    x, y, z = grid_coord
    
    if adjacent_mode:
        # 相邻模式：根据模型实际尺寸计算位置
        world_x = x * model_size_x
        world_y = y * model_size_y
        world_z = z * model_size_z  # 修复：Z轴也应该使用模型尺寸
    else:
        # 非相邻模式：使用基础网格大小
        world_x = x * base_block_size
        world_y = y * base_block_size
        world_z = z * base_block_size
    
    # 处理定位模式
    if not use_model_center:
        # 模型底部对齐：将模型底部放在网格平面上
        pass
    else:
        # 模型中心对齐：需要将模型中心放在计算的位置上
        world_z += model_size_z / 2
    
    return world_x, world_y, world_z

def align_object_to_grid(obj, base_block_size, use_model_center=False):
    """将对象对齐到网格"""
    # 计算当前对象的边界框尺寸
    size_x, size_y, size_z, max_size = calculate_model_dimensions(obj)
    
    # 计算当前对象的中心
    center = calculate_model_center(obj)
    
    # 计算最近的网格点
    grid_x = round(center.x / base_block_size) * base_block_size
    grid_y = round(center.y / base_block_size) * base_block_size
    
    if use_model_center:
        grid_z = round(center.z / base_block_size) * base_block_size
    else:
        # 底部对齐
        bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
        z_coords = [corner.z for corner in bbox_corners]
        min_z = min(z_coords)
        grid_z = round(min_z / base_block_size) * base_block_size
    
    # 计算新的位置
    new_pos_x = grid_x
    new_pos_y = grid_y
    
    if use_model_center:
        new_pos_z = grid_z
    else:
        new_pos_z = grid_z + size_z / 2
    
    # 移动对象到网格点
    current_pos = obj.location
    obj.location = (new_pos_x, new_pos_y, new_pos_z)
    
    return current_pos, obj.location

# ============================================================================
# 面检测函数
# ============================================================================

def find_all_directional_faces(obj):
    """查找所有方向面：X、-X、Y、-Y、Z、-Z"""
    x_faces = []      # +X面
    neg_x_faces = []  # -X面
    y_faces = []      # +Y面
    neg_y_faces = []  # -Y面
    z_faces = []      # +Z面
    neg_z_faces = []  # -Z面
    
    if obj.type != 'MESH':
        return x_faces, neg_x_faces, y_faces, neg_y_faces, z_faces, neg_z_faces
    
    mesh = obj.data
    
    for poly in mesh.polygons:
        normal = poly.normal
        if normal.length > 0:
            normal_normalized = normal.normalized()
        else:
            normal_normalized = normal
        
        # 检查+X面（法线≈(1,0,0)）
        if normal_normalized.x > 0.7 and abs(normal_normalized.y) < 0.3 and abs(normal_normalized.z) < 0.3:
            x_faces.append(poly.index)
        # 检查-X面（法线≈(-1,0,0)）
        elif normal_normalized.x < -0.7 and abs(normal_normalized.y) < 0.3 and abs(normal_normalized.z) < 0.3:
            neg_x_faces.append(poly.index)
        # 检查+Y面（法线≈(0,1,0)）
        elif normal_normalized.y > 0.7 and abs(normal_normalized.x) < 0.3 and abs(normal_normalized.z) < 0.3:
            y_faces.append(poly.index)
        # 检查-Y面（法线≈(0,-1,0)）
        elif normal_normalized.y < -0.7 and abs(normal_normalized.x) < 0.3 and abs(normal_normalized.z) < 0.3:
            neg_y_faces.append(poly.index)
        # 检查+Z面（法线≈(0,0,1)）
        elif normal_normalized.z > 0.7 and abs(normal_normalized.x) < 0.3 and abs(normal_normalized.y) < 0.3:
            z_faces.append(poly.index)
        # 检查-Z面（法线≈(0,0,-1)）
        elif normal_normalized.z < -0.7 and abs(normal_normalized.x) < 0.3 and abs(normal_normalized.y) < 0.3:
            neg_z_faces.append(poly.index)
    
    return x_faces, neg_x_faces, y_faces, neg_y_faces, z_faces, neg_z_faces

def find_x_faces_simple(obj):
    """查找X面和-X面"""
    x_faces = []      # +X面
    neg_x_faces = []  # -X面
    
    if obj.type != 'MESH':
        return x_faces, neg_x_faces
    
    mesh = obj.data
    
    for poly in mesh.polygons:
        normal = poly.normal
        if normal.length > 0:
            normal_normalized = normal.normalized()
        else:
            normal_normalized = normal
        
        # 检查+X面（法线≈(1,0,0)）
        if normal_normalized.x > 0.7 and abs(normal_normalized.y) < 0.3 and abs(normal_normalized.z) < 0.3:
            x_faces.append(poly.index)
        # 检查-X面（法线≈(-1,0,0)）
        elif normal_normalized.x < -0.7 and abs(normal_normalized.y) < 0.3 and abs(normal_normalized.z) < 0.3:
            neg_x_faces.append(poly.index)
    
    return x_faces, neg_x_faces

# ============================================================================
# 材质相关函数
# ============================================================================

def create_green_material():
    """创建或获取绿色共享材质（用于源模型检查）- 全局共享"""
    green_material_name = "Green_Material_X_Faces"
    green_color = (0.0, 1.0, 0.0, 1.0)  # 纯绿色 RGBA
    
    # 检查是否已存在该材质
    if green_material_name in bpy.data.materials:
        mat = bpy.data.materials[green_material_name]
        return mat
    else:
        # 创建新材质
        mat = bpy.data.materials.new(name=green_material_name)
        mat.use_nodes = True
        nodes = mat.node_tree.nodes
        nodes.clear()
        
        # 创建Principled BSDF节点
        principled = nodes.new(type='ShaderNodeBsdfPrincipled')
        principled.location = (0, 0)
        principled.inputs['Base Color'].default_value = green_color
        principled.inputs['Roughness'].default_value = 0.5
        
        # 兼容Blender 4.0
        try:
            if 'Specular' in principled.inputs:
                principled.inputs['Specular'].default_value = 0.0
            elif 'Specular IOR Level' in principled.inputs:
                principled.inputs['Specular IOR Level'].default_value = 0.0
        except:
            pass
        
        try:
            if 'Metallic' in principled.inputs:
                principled.inputs['Metallic'].default_value = 0.0
        except:
            pass
        
        # 兼容Blender 4.0：尝试设置次表面散射输入
        try:
            if 'Subsurface' in principled.inputs:
                principled.inputs['Subsurface'].default_value = 0.0
            elif 'Subsurface Weight' in principled.inputs:
                principled.inputs['Subsurface Weight'].default_value = 0.0
        except:
            pass
        
        output = nodes.new(type='ShaderNodeOutputMaterial')
        output.location = (400, 0)
        
        # 连接节点
        links = mat.node_tree.links
        links.new(principled.outputs['BSDF'], output.inputs['Surface'])
        
        return mat

def apply_green_material_to_x_faces(obj):
    """为X面和-X面应用绿色材质（仅用于源模型检查）"""
    if obj.type != 'MESH':
        print(f"错误: 对象 {obj.name} 不是网格类型")
        return 0
    
    # 获取X面和-X面
    x_faces, neg_x_faces = find_x_faces_simple(obj)
    all_x_faces = x_faces + neg_x_faces
    
    if not all_x_faces:
        print(f"对象 {obj.name} 没有找到X面或-X面")
        return 0
    
    # 创建或获取绿色材质（全局共享）
    green_material = create_green_material()
    
    # 检查绿色材质是否已在对象材质列表中
    material_index = -1
    for i, mat in enumerate(obj.data.materials):
        if mat and mat.name == "Green_Material_X_Faces":
            material_index = i
            break
    
    # 如果不在，添加它
    if material_index == -1:
        obj.data.materials.append(green_material)
        material_index = len(obj.data.materials) - 1
    
    # 应用材质到X面和-X面
    applied_count = 0
    for face_idx in all_x_faces:
        if face_idx < len(obj.data.polygons):
            poly = obj.data.polygons[face_idx]
            poly.material_index = material_index
            applied_count += 1
    
    obj.data.update()
    
    return applied_count

def load_texture_image(texture_path):
    """加载贴图图片"""
    if not texture_path or not os.path.exists(texture_path):
        print(f"贴图文件不存在: {texture_path}")
        return None
    
    try:
        # 获取文件名
        tex_name = os.path.basename(texture_path)
        
        # 检查是否已存在同名图像
        if tex_name in bpy.data.images:
            image = bpy.data.images[tex_name]
        else:
            # 加载新图像
            image = bpy.data.images.load(texture_path)
        
        return image
        
    except Exception as e:
        print(f"✗ 加载贴图失败 {texture_path}: {e}")
        return None

def create_face_material_node_tree(material, position_id, texture_path, face_type='x', is_x_face=True, is_submodel=False):
    """创建包含图像纹理的材质节点树（针对特定面类型）- 修复Z面和-Z面的UV映射"""
    # 确保使用节点
    material.use_nodes = True
    
    # 获取材质节点树
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    
    # 清除所有现有节点
    nodes.clear()
    
    # 创建输出节点
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)
    
    # 创建Principled BSDF节点
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf_node.location = (0, 0)
    bsdf_node.inputs['Roughness'].default_value = 0.5
    
    # 兼容Blender 4.0：尝试设置Specular输入（如果存在）
    try:
        if 'Specular' in bsdf_node.inputs:
            bsdf_node.inputs['Specular'].default_value = 0.0
        elif 'Specular IOR Level' in bsdf_node.inputs:
            bsdf_node.inputs['Specular IOR Level'].default_value = 0.0
    except:
        pass
    
    # 兼容Blender 4.0：尝试设置Metallic输入（如果存在）
    try:
        if 'Metallic' in bsdf_node.inputs:
            bsdf_node.inputs['Metallic'].default_value = 0.0
    except:
        pass
    
    # 兼容Blender 4.0：尝试设置次表面散射输入
    try:
        if 'Subsurface' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface'].default_value = 0.0
        elif 'Subsurface Weight' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface Weight'].default_value = 0.0
    except:
        pass
    
    # 连接BSDF到输出
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
    
    # 如果有贴图，创建图像纹理节点
    if texture_path:
        # 加载图像
        texture_image = load_texture_image(texture_path)
        
        if texture_image:
            # 创建图像纹理节点
            texture_node = nodes.new(type='ShaderNodeTexImage')
            texture_node.location = (-300, 0)
            texture_node.image = texture_image
            
            # 创建纹理坐标节点
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-500, 0)
            
            # 创建映射节点
            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-350, 0)
            mapping.vector_type = 'TEXTURE'
            
            # Z面和-Z面的特殊处理：镜像X轴并向左旋转90度
            if face_type.lower() == 'z':
                # 镜像X轴
                mapping.inputs['Scale'].default_value = (-1.0, 1.0, 1.0)
                # 向左旋转90度（绕Z轴旋转-90度）
                mapping.inputs['Rotation'].default_value = (0.0, 0.0, -math.pi/2)
            
            # 连接节点
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])
            links.new(mapping.outputs['Vector'], texture_node.inputs['Vector'])
            links.new(texture_node.outputs['Color'], bsdf_node.inputs['Base Color'])
            
            return True
        else:
            # 如果贴图加载失败，使用纯色
            if is_submodel:
                bsdf_node.inputs['Base Color'].default_value = (0.5, 0.5, 0.8, 1.0)  # 子模型蓝色
            elif face_type.lower() == 'x':
                bsdf_node.inputs['Base Color'].default_value = (1.0, 0.0, 0.0, 1.0)  # 红色
            elif face_type.lower() == 'y':
                bsdf_node.inputs['Base Color'].default_value = (0.0, 1.0, 0.0, 1.0)  # 绿色
            elif face_type.lower() == 'z':
                bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 1.0, 1.0)  # 蓝色
            else:
                bsdf_node.inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1.0)  # 灰色
            return False
    else:
        # 如果没有贴图，使用纯色
        if is_submodel:
            bsdf_node.inputs['Base Color'].default_value = (0.5, 0.5, 0.8, 1.0)  # 子模型蓝色
        elif face_type.lower() == 'x':
            bsdf_node.inputs['Base Color'].default_value = (1.0, 0.0, 0.0, 1.0)  # 红色
        elif face_type.lower() == 'y':
            bsdf_node.inputs['Base Color'].default_value = (0.0, 1.0, 0.0, 1.0)  # 绿色
        elif face_type.lower() == 'z':
            bsdf_node.inputs['Base Color'].default_value = (0.0, 0.0, 1.0, 1.0)  # 蓝色
        else:
            bsdf_node.inputs['Base Color'].default_value = (0.8, 0.8, 0.8, 1.0)  # 灰色
        return False

def create_teamspawn_material_node_tree(material, texture_path):
    """为teamspawn类型创建材质节点树 - 只使用一个材质球，贴图处理模型和正常数组相反"""
    # 确保使用节点
    material.use_nodes = True
    
    # 获取材质节点树
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    
    # 清除所有现有节点
    nodes.clear()
    
    # 创建输出节点
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)
    
    # 创建Principled BSDF节点
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf_node.location = (0, 0)
    bsdf_node.inputs['Roughness'].default_value = 0.5
    
    # 兼容Blender 4.0：尝试设置Specular输入（如果存在）
    try:
        if 'Specular' in bsdf_node.inputs:
            bsdf_node.inputs['Specular'].default_value = 0.0
        elif 'Specular IOR Level' in bsdf_node.inputs:
            bsdf_node.inputs['Specular IOR Level'].default_value = 0.0
    except:
        pass
    
    # 兼容Blender 4.0：尝试设置Metallic输入（如果存在）
    try:
        if 'Metallic' in bsdf_node.inputs:
            bsdf_node.inputs['Metallic'].default_value = 0.0
    except:
        pass
    
    # 兼容Blender 4.0：尝试设置次表面散射输入
    try:
        if 'Subsurface' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface'].default_value = 0.0
        elif 'Subsurface Weight' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface Weight'].default_value = 0.0
    except:
        pass
    
    # 连接BSDF到输出
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
    
    # 如果有贴图，创建图像纹理节点
    if texture_path:
        # 加载图像
        texture_image = load_texture_image(texture_path)
        
        if texture_image:
            # 创建图像纹理节点
            texture_node = nodes.new(type='ShaderNodeTexImage')
            texture_node.location = (-300, 0)
            texture_node.image = texture_image
            
            # 创建纹理坐标节点
            tex_coord = nodes.new(type='ShaderNodeTexCoord')
            tex_coord.location = (-500, 0)
            
            # teamspawn类型：贴图处理模型和正常数组相反
            # 创建映射节点
            mapping = nodes.new(type='ShaderNodeMapping')
            mapping.location = (-350, 0)
            mapping.vector_type = 'TEXTURE'
            
            # 对于teamspawn类型，可能需要特殊的UV映射
            # 这里可以根据需要调整，例如镜像X轴或旋转等
            # 暂时不进行特殊处理，保持默认
            # mapping.inputs['Scale'].default_value = (-1.0, 1.0, 1.0)  # 如果需要镜像X轴
            # mapping.inputs['Rotation'].default_value = (0.0, 0.0, math.pi/2)  # 如果需要旋转
            
            # 连接节点
            links.new(tex_coord.outputs['UV'], mapping.inputs['Vector'])
            links.new(mapping.outputs['Vector'], texture_node.inputs['Vector'])
            links.new(texture_node.outputs['Color'], bsdf_node.inputs['Base Color'])
            
            return True
        else:
            # 如果贴图加载失败，使用纯色（黄色，以便区分）
            bsdf_node.inputs['Base Color'].default_value = (1.0, 1.0, 0.0, 1.0)  # 黄色
            return False
    else:
        # 如果没有贴图，使用纯色（黄色，以便区分）
        bsdf_node.inputs['Base Color'].default_value = (1.0, 1.0, 0.0, 1.0)  # 黄色
        return False

def create_submodel_material_node_tree(material, diffuse_texture_path=None, emission_texture_path=None, emission_strength=2.6):
    """为子模型创建包含自发光贴图的材质节点树（简化版）- 兼容Blender 4.0"""
    # 确保使用节点
    material.use_nodes = True
    
    # 获取材质节点树
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    
    # 清除所有现有节点
    nodes.clear()
    
    # 创建节点布局 - 简化布局
    output_location = (300, 0)
    add_shader_location = (0, 0)
    principled_location = (-300, 100)
    emission_location = (-300, -100)
    diffuse_tex_location = (-600, 100)
    emission_tex_location = (-600, -100)
    
    # 1. 创建输出节点
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = output_location
    
    # 2. 创建混合着色器节点（相加）
    add_shader = nodes.new(type='ShaderNodeAddShader')
    add_shader.location = add_shader_location
    
    has_diffuse = False
    has_emission = False
    
    diffuse_tex = None
    emission_tex = None
    
    # 3. 创建漫反射贴图节点（如果存在）
    if diffuse_texture_path:
        diffuse_image = load_texture_image(diffuse_texture_path)
        if diffuse_image:
            diffuse_tex = nodes.new(type='ShaderNodeTexImage')
            diffuse_tex.location = diffuse_tex_location
            diffuse_tex.image = diffuse_image
            
            # Blender 4.0兼容性：设置颜色空间
            try:
                # Blender 4.0+ 使用新的API
                diffuse_tex.image.colorspace_settings.name = 'sRGB'
            except AttributeError:
                # Blender 3.x 兼容性
                try:
                    diffuse_tex.color_space = 'COLOR'
                except:
                    pass
            
            diffuse_tex.interpolation = 'Closest'  # Flat插值模式
            diffuse_tex.extension = 'REPEAT'
            has_diffuse = True
    
    # 4. 创建自发光贴图节点（如果存在）
    if emission_texture_path:
        emission_image = load_texture_image(emission_texture_path)
        if emission_image:
            emission_tex = nodes.new(type='ShaderNodeTexImage')
            emission_tex.location = emission_tex_location
            emission_tex.image = emission_image
            
            # Blender 4.0兼容性：设置颜色空间
            try:
                # Blender 4.0+ 使用新的API
                emission_tex.image.colorspace_settings.name = 'sRGB'
            except AttributeError:
                # Blender 3.x 兼容性
                try:
                    emission_tex.color_space = 'COLOR'
                except:
                    pass
            
            emission_tex.interpolation = 'Closest'  # Flat插值模式
            emission_tex.extension = 'REPEAT'
            has_emission = True
    
    # 5. 创建Principled BSDF节点
    principled = nodes.new(type='ShaderNodeBsdfPrincipled')
    principled.location = principled_location
    principled.inputs['Metallic'].default_value = 0.000
    principled.inputs['Roughness'].default_value = 0.500
    principled.inputs['IOR'].default_value = 1.450
    principled.inputs['Alpha'].default_value = 1.000
    
    # Blender 4.0兼容性：尝试设置次表面散射（Subsurface）输入
    try:
        if 'Subsurface' in principled.inputs:
            principled.inputs['Subsurface'].default_value = 0.0
        elif 'Subsurface Weight' in principled.inputs:  # Blender 4.0中的新名称
            principled.inputs['Subsurface Weight'].default_value = 0.0
    except:
        pass  # 如果不存在，跳过
    
    # 兼容Blender 4.0：尝试设置Specular输入
    try:
        if 'Specular' in principled.inputs:
            principled.inputs['Specular'].default_value = 0.0
        elif 'Specular IOR Level' in principled.inputs:
            principled.inputs['Specular IOR Level'].default_value = 0.0
    except:
        pass
    
    # 连接漫反射贴图到Principled BSDF
    if has_diffuse:
        links.new(diffuse_tex.outputs['Color'], principled.inputs['Base Color'])
        links.new(diffuse_tex.outputs['Alpha'], principled.inputs['Alpha'])
    else:
        # 默认颜色
        principled.inputs['Base Color'].default_value = (0.5, 0.5, 0.8, 1.0)
    
    # 6. 创建自发光节点
    emission = nodes.new(type='ShaderNodeEmission')
    emission.location = emission_location
    emission.inputs['Strength'].default_value = emission_strength
    
    # 连接自发光贴图到自发光节点
    if has_emission:
        links.new(emission_tex.outputs['Color'], emission.inputs['Color'])
    else:
        # 如果没有自发光贴图，使用默认颜色或漫反射颜色
        if has_diffuse:
            # 使用漫反射颜色作为自发光
            links.new(diffuse_tex.outputs['Color'], emission.inputs['Color'])
        else:
            emission.inputs['Color'].default_value = (0.8, 0.8, 0.8, 1.0)
    
    # 7. 连接Principled BSDF和自发光到混合着色器
    links.new(principled.outputs['BSDF'], add_shader.inputs[0])
    links.new(emission.outputs['Emission'], add_shader.inputs[1])
    
    # 8. 连接混合着色器到输出
    links.new(add_shader.outputs['Shader'], output_node.inputs['Surface'])
    
    # 修复：确保所有节点都正确连接
    # 检查是否有未连接的节点
    for node in nodes:
        if node.type == 'TEX_IMAGE':
            if node.image:
                print(f"  图像纹理节点: {node.image.name}")
                # 确保图像已加载
                if node.image.filepath and not node.image.has_data:
                    try:
                        node.image.reload()
                    except:
                        print(f"    警告: 无法重新加载图像 {node.image.name}")
    
    return has_diffuse, has_emission

def get_material_name_for_face(position_id, face_type='x'):
    """根据位置ID和面类型生成材质名称"""
    return f"BlockMat_{face_type.upper()}_{position_id}"

def get_material_name_for_submodel(position_id, submodel_name, has_emission=False):
    """根据位置ID和子模型名称生成材质名称"""
    if has_emission:
        return f"BlockMat_Sub_{position_id}_{submodel_name}_emi"
    else:
        return f"BlockMat_Sub_{position_id}_{submodel_name}"

def get_default_material_name(position_id):
    """获取默认材质名称"""
    return f"BlockMat_Default_{position_id}"

def get_unified_material_name(position_id):
    """获取统一材质名称（用于所有面使用同一个贴图的情况）"""
    return f"BlockMat_Unified_{position_id}"

def get_teamspawn_material_name(position_id):
    """获取teamspawn类型材质名称（只使用一个材质球）"""
    return f"BlockMat_Teamspawn_{position_id}"

def create_or_get_face_material(position_id, texture_path, face_type='x'):
    """创建或获取面材质（共享材质系统）- 修复名称重复问题"""
    manager = BlockModelManager()
    
    # 修复：生成唯一材质名称，避免重复
    # 使用更简单的命名规则，避免Blender自动添加后缀
    mat_name = f"BlockMat_{face_type.upper()}_{position_id}"
    
    # 修复：清理已存在的重复材质
    if mat_name in bpy.data.materials:
        # 检查是否是我们需要的材质
        existing_mat = bpy.data.materials[mat_name]
        # 如果材质已经有用户，并且不是我们需要的（比如名称被Blender修改过）
        # 则创建新的唯一名称
        if existing_mat.users > 0 and existing_mat.name != mat_name:
            # 找到真正唯一的名称
            base_name = f"BlockMat_{face_type.upper()}_{position_id}"
            counter = 1
            while f"{base_name}.{str(counter).zfill(3)}" in bpy.data.materials:
                counter += 1
            mat_name = f"{base_name}.{str(counter).zfill(3)}"
    
    # 检查是否已存在材质（包括可能的重命名版本）
    existing_mat = manager.get_material(mat_name)
    if existing_mat:
        return existing_mat
    
    # 检查Blender中是否已存在同名材质
    if mat_name in bpy.data.materials:
        material = bpy.data.materials[mat_name]
        manager.set_material(mat_name, material)
        return material
    
    # 创建新材质
    material = bpy.data.materials.new(name=mat_name)
    
    # 创建材质节点树
    create_face_material_node_tree(material, position_id, texture_path, face_type, is_x_face=(face_type.lower() == 'x'))
    
    manager.set_material(mat_name, material)
    
    return material

def create_or_get_teamspawn_material(position_id, texture_path):
    """创建或获取teamspawn类型材质（只使用一个材质球）"""
    manager = BlockModelManager()
    
    # 生成材质名称
    mat_name = get_teamspawn_material_name(position_id)
    
    # 检查是否已存在材质
    existing_mat = manager.get_material(mat_name)
    if existing_mat:
        return existing_mat
    
    # 创建新材质
    material = bpy.data.materials.new(name=mat_name)
    
    # 创建teamspawn类型材质节点树
    create_teamspawn_material_node_tree(material, texture_path)
    
    manager.set_material(mat_name, material)
    
    return material

def create_or_get_unified_material(position_id, texture_path):
    """创建或获取统一材质（所有面使用同一个贴图）"""
    manager = BlockModelManager()
    
    # 生成材质名称
    mat_name = get_unified_material_name(position_id)
    
    # 检查是否已存在材质
    existing_mat = manager.get_material(mat_name)
    if existing_mat:
        return existing_mat
    
    # 创建新材质
    material = bpy.data.materials.new(name=mat_name)
    
    # 创建材质节点树，使用'x'作为默认面类型
    create_face_material_node_tree(material, position_id, texture_path, 'x', is_x_face=True)
    
    manager.set_material(mat_name, material)
    
    return material

def create_or_get_submodel_material(position_id, diffuse_texture_path=None, emission_texture_path=None, submodel_name=None, emission_strength=2.6):
    """创建或获取子模型材质（支持自发光贴图）"""
    manager = BlockModelManager()
    
    # 检查是否缺少子模型名称
    if not submodel_name:
        # 尝试从映射数据获取
        mapping_data = manager.get_mapping_for_id(position_id)
        if mapping_data:
            submodel_name = mapping_data.get('submodel_name', f"submodel_{position_id}")
        else:
            submodel_name = f"submodel_{position_id}"
    
    # 确定是否有自发光贴图
    has_emission = emission_texture_path is not None and os.path.exists(emission_texture_path) if emission_texture_path else False
    
    # 生成材质名称
    mat_name = get_material_name_for_submodel(position_id, submodel_name, has_emission)
    
    # 检查是否已存在材质
    existing_mat = manager.get_material(mat_name)
    if existing_mat:
        return existing_mat
    
    # 创建新材质
    material = bpy.data.materials.new(name=mat_name)
    
    # 创建材质节点树（支持自发光贴图）
    has_diffuse, has_emission_actual = create_submodel_material_node_tree(
        material, 
        diffuse_texture_path, 
        emission_texture_path,
        emission_strength
    )
    
    # 记录材质信息
    material["is_submodel_material"] = True
    material["position_id"] = position_id
    material["submodel_name"] = submodel_name
    material["has_emission"] = has_emission_actual
    material["has_diffuse"] = has_diffuse
    
    manager.set_material(mat_name, material)
    
    print(f"✓ 创建子模型材质: {mat_name}")
    print(f"  漫反射贴图: {'有' if has_diffuse else '无'}")
    print(f"  自发光贴图: {'有' if has_emission_actual else '无'}")
    if has_emission_actual:
        print(f"  自发光强度: {emission_strength}")
    
    return material

def create_or_get_default_material(position_id):
    """创建或获取默认材质（用于非定向面）"""
    manager = BlockModelManager()
    
    # 生成材质名称
    mat_name = get_default_material_name(position_id)
    
    # 检查是否已存在材质
    existing_mat = manager.get_material(mat_name)
    if existing_mat:
        return existing_mat
    
    # 创建新材质
    material = bpy.data.materials.new(name=mat_name)
    material.use_nodes = True
    
    # 获取材质节点
    nodes = material.node_tree.nodes
    links = material.node_tree.links
    
    # 清除所有默认节点
    for node in nodes:
        nodes.remove(node)
    
    # 创建输出节点
    output_node = nodes.new(type='ShaderNodeOutputMaterial')
    output_node.location = (300, 0)
    
    # 创建Principled BSDF节点
    bsdf_node = nodes.new(type='ShaderNodeBsdfPrincipled')
    bsdf_node.location = (0, 0)
    
    # 基于位置ID生成颜色（绿色系，以便区分）
    import random
    random.seed(position_id + 2000)  # 加偏移确保与其他材质颜色不同
    hue = 0.3  # 绿色系
    saturation = random.random() * 0.3 + 0.3
    value = random.random() * 0.3 + 0.4
    from colorsys import hsv_to_rgb
    r, g, b = hsv_to_rgb(hue, saturation, value)
    bsdf_node.inputs['Base Color'].default_value = (r, g, b, 1.0)
    bsdf_node.inputs['Roughness'].default_value = 0.8
    
    # 兼容Blender 4.0
    try:
        if 'Specular' in bsdf_node.inputs:
            bsdf_node.inputs['Specular'].default_value = 0.0
        elif 'Specular IOR Level' in bsdf_node.inputs:
            bsdf_node.inputs['Specular IOR Level'].default_value = 0.0
    except:
        pass
    
    try:
        if 'Metallic' in bsdf_node.inputs:
            bsdf_node.inputs['Metallic'].default_value = 0.0
    except:
        pass
    
    # 兼容Blender 4.0：尝试设置次表面散射输入
    try:
        if 'Subsurface' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface'].default_value = 0.0
        elif 'Subsurface Weight' in bsdf_node.inputs:
            bsdf_node.inputs['Subsurface Weight'].default_value = 0.0
    except:
        pass
    
    # 连接BSDF到输出
    links.new(bsdf_node.outputs['BSDF'], output_node.inputs['Surface'])
    
    manager.set_material(mat_name, material)
    
    return material

def apply_main_model_materials(obj, position_id, texture_base_path, mapping_data):
    """为主模型应用材质 - 根据材质系统决定使用哪种材质系统"""
    print(f"为主模型 {obj.name} 应用材质...")
    
    # 清空现有材质
    if len(obj.data.materials) > 0:
        obj.data.materials.clear()
    
    # 获取模型配置
    model_config = BlockModelManager().get_model_config(position_id)
    if not model_config:
        print(f"错误: 找不到位置ID {position_id} 的模型配置")
        return False
    
    # 根据材质系统选择材质系统
    if model_config.material_system == 'teamspawn_system':
        # teamspawn类型：只使用一个材质球，贴图处理模型和正常数组相反
        return apply_teamspawn_material_system(obj, position_id, model_config)
    elif model_config.material_system == 'soil_system':
        # soil/plantash类型：Z面特殊，其他面使用主贴图
        return apply_soil_material_system(obj, position_id, model_config)
    elif model_config.material_system == 'minestone_system':
        # minestone类型：X、Y、Z面独立调配，每个面使用自己的贴图
        return apply_minestone_material_system(obj, position_id, model_config)
    elif model_config.material_system == 'submodel_only':
        # replicator/airwall/copier类型：只创建子模型，不需要主模型
        print(f"Blocktype {model_config.blocktype} 不需要主模型材质")
        return True
    else:
        # 默认：标准XYZ面贴图
        return apply_default_material_system(obj, position_id, model_config)

def apply_teamspawn_material_system(obj, position_id, model_config):
    """应用teamspawn类型材质系统：只使用一个材质球，贴图处理模型和正常数组相反"""
    print(f"应用teamspawn类型材质系统...")
    
    # 获取贴图路径
    texture_path = model_config._get_teamspawn_texture_path()
    
    print(f"teamspawn贴图: {os.path.basename(texture_path) if texture_path else '无'}")
    
    # 创建或获取teamspawn材质
    teamspawn_mat = None
    
    if texture_path:
        # 创建teamspawn材质（只使用一个材质球）
        teamspawn_mat = create_or_get_teamspawn_material(position_id, texture_path)
    
    # 如果没有贴图，使用默认材质
    default_mat = create_or_get_default_material(position_id)
    
    # 添加材质到对象
    if teamspawn_mat:
        obj.data.materials.append(teamspawn_mat)
        print(f"✓ 已添加teamspawn材质: {teamspawn_mat.name}")
    else:
        obj.data.materials.append(default_mat)
        print(f"⚠ 使用默认材质替代teamspawn材质")
    
    # 所有面使用同一个材质索引
    for poly in obj.data.polygons:
        poly.material_index = 0
    
    obj.data.update()
    
    print(f"✓ 已应用teamspawn类型材质系统")
    print(f"  所有面使用同一个材质球: {teamspawn_mat.name if teamspawn_mat else default_mat.name}")
    print(f"  应用于 {len(obj.data.polygons)} 个面")
    
    return True

def apply_soil_material_system(obj, position_id, model_config):
    """应用soil类型材质系统：Z面特殊，其他面使用主贴图"""
    print(f"应用soil类型材质系统...")
    
    # 获取贴图路径
    main_texture_path = model_config.get_texture_path('x')  # 主贴图（用于X、-X、Y、-Y、-Z面）
    z_texture_path = model_config.get_texture_path('z')     # Z面特殊贴图
    
    print(f"主贴图: {os.path.basename(main_texture_path) if main_texture_path else '无'}")
    print(f"Z面贴图: {os.path.basename(z_texture_path) if z_texture_path else '无'}")
    
    # 修复：如果没有Z面特殊贴图，使用主贴图作为Z面贴图
    if not z_texture_path and main_texture_path:
        print(f"警告：未找到Z面特殊贴图，将使用主贴图作为Z面贴图")
        z_texture_path = main_texture_path
    
    # 创建或获取材质
    main_mat = None
    z_mat = None
    
    if main_texture_path:
        # 创建主材质（用于X、-X、Y、-Y、-Z面）
        main_mat = create_or_get_face_material(position_id, main_texture_path, 'x')
    
    if z_texture_path:
        # 创建Z面材质
        z_mat = create_or_get_face_material(position_id, z_texture_path, 'z')
    
    # 如果没有贴图，使用默认材质
    default_mat = create_or_get_default_material(position_id)
    
    # 添加材质到对象
    material_indices = {}
    if main_mat:
        obj.data.materials.append(main_mat)
        material_indices['main'] = 0
    if z_mat:
        obj.data.materials.append(z_mat)
        material_indices['z'] = len(obj.data.materials) - 1
    if not main_mat and not z_mat:
        obj.data.materials.append(default_mat)
        material_indices['default'] = 0
    
    # 找到所有方向面
    x_faces, neg_x_faces, y_faces, neg_y_faces, z_faces, neg_z_faces = find_all_directional_faces(obj)
    
    # 检查是否有面
    if len(obj.data.polygons) == 0:
        print(f"警告: 对象 {obj.name} 没有面")
        return False
    
    # 应用材质索引
    main_count = 0
    z_count = 0
    default_count = 0
    
    for poly in obj.data.polygons:
        if poly.index in z_faces:  # +Z面使用Z面特殊材质
            if 'z' in material_indices:
                poly.material_index = material_indices['z']
                z_count += 1
            elif 'main' in material_indices:
                poly.material_index = material_indices['main']
                main_count += 1
            else:
                poly.material_index = material_indices['default']
                default_count += 1
        elif poly.index in neg_z_faces:  # -Z面使用主材质
            if 'main' in material_indices:
                poly.material_index = material_indices['main']
                main_count += 1
            else:
                poly.material_index = material_indices['default']
                default_count += 1
        else:
            # X、-X、Y、-Y面使用主材质
            if 'main' in material_indices:
                poly.material_index = material_indices['main']
                main_count += 1
            else:
                poly.material_index = material_indices['default']
                default_count += 1
    
    obj.data.update()
    
    print(f"✓ 已应用soil类型材质系统")
    print(f"  主材质: 应用于 {main_count} 个面（X、-X、Y、-Y、-Z）")
    print(f"  Z面材质: 应用于 {z_count} 个面（+Z）")
    print(f"  默认材质: 应用于 {default_count} 个面")
    
    return True

def apply_minestone_material_system(obj, position_id, model_config):
    """应用minestone类型材质系统：X、Y、Z面独立调配，每个面使用自己的贴图"""
    print(f"应用minestone类型材质系统...")
    
    # 获取各面贴图路径 - minestone类型各面独立
    x_texture_path = model_config.get_texture_path('x')
    y_texture_path = model_config.get_texture_path('y')
    z_texture_path = model_config.get_texture_path('z')
    
    print(f"X面贴图: {os.path.basename(x_texture_path) if x_texture_path else '无'}")
    print(f"Y面贴图: {os.path.basename(y_texture_path) if y_texture_path else '无'}")
    print(f"Z面贴图: {os.path.basename(z_texture_path) if z_texture_path else '无'}")
    
    # 如果没有贴图，使用默认材质
    if not x_texture_path and not y_texture_path and not z_texture_path:
        default_mat = create_or_get_default_material(position_id)
        obj.data.materials.append(default_mat)
        
        # 所有面使用默认材质
        for poly in obj.data.polygons:
            poly.material_index = 0
        
        obj.data.update()
        print(f"✓ 已为主模型应用默认材质: {default_mat.name}")
        return True
    
    # 创建或获取共享材质 - 为X、Y、Z面分别创建独立的材质
    x_mat = None
    y_mat = None
    z_mat = None
    
    if x_texture_path:
        x_mat = create_or_get_face_material(position_id, x_texture_path, 'x')
    if y_texture_path:
        y_mat = create_or_get_face_material(position_id, y_texture_path, 'y')
    if z_texture_path:
        z_mat = create_or_get_face_material(position_id, z_texture_path, 'z')
    
    # 创建或获取默认材质
    default_mat = create_or_get_default_material(position_id)
    
    # 添加材质到对象
    material_indices = {}
    if x_mat:
        obj.data.materials.append(x_mat)
        material_indices['x'] = len(obj.data.materials) - 1
    if y_mat:
        obj.data.materials.append(y_mat)
        material_indices['y'] = len(obj.data.materials) - 1
    if z_mat:
        obj.data.materials.append(z_mat)
        material_indices['z'] = len(obj.data.materials) - 1
    if not x_mat and not y_mat and not z_mat:
        obj.data.materials.append(default_mat)
        material_indices['default'] = 0
    
    # 找到所有方向面
    x_faces, neg_x_faces, y_faces, neg_y_faces, z_faces, neg_z_faces = find_all_directional_faces(obj)
    
    # 检查是否有面
    if len(obj.data.polygons) == 0:
        print(f"警告: 对象 {obj.name} 没有面")
        return False
    
    # 应用材质索引
    x_count = 0
    y_count = 0
    z_count = 0
    default_count = 0
    
    for poly in obj.data.polygons:
        if poly.index in x_faces or poly.index in neg_x_faces:
            if 'x' in material_indices:
                poly.material_index = material_indices['x']
                x_count += 1
            elif 'default' in material_indices:
                poly.material_index = material_indices['default']
                default_count += 1
        elif poly.index in y_faces or poly.index in neg_y_faces:
            if 'y' in material_indices:
                poly.material_index = material_indices['y']
                y_count += 1
            elif 'default' in material_indices:
                poly.material_index = material_indices['default']
                default_count += 1
        elif poly.index in z_faces or poly.index in neg_z_faces:
            if 'z' in material_indices:
                poly.material_index = material_indices['z']
                z_count += 1
            elif 'default' in material_indices:
                poly.material_index = material_indices['default']
                default_count += 1
        else:
            if 'default' in material_indices:
                poly.material_index = material_indices['default']
                default_count += 1
    
    obj.data.update()
    
    print(f"✓ 已应用minestone类型材质系统")
    print(f"  X面材质: 应用于 {x_count} 个面（+X和-X）")
    print(f"  Y面材质: 应用于 {y_count} 个面（+Y和-Y）")
    print(f"  Z面材质: 应用于 {z_count} 个面（+Z和-Z，已应用正确的UV映射）")
    print(f"  默认材质: 应用于 {default_count} 个非定向面")
    
    return True

def apply_default_material_system(obj, position_id, model_config):
    """应用默认材质系统：标准XYZ面贴图"""
    print(f"应用默认材质系统...")
    
    # 获取各面贴图路径
    x_texture_path = model_config.get_texture_path('x')
    y_texture_path = model_config.get_texture_path('y')
    z_texture_path = model_config.get_texture_path('z')
    
    print(f"X面贴图: {os.path.basename(x_texture_path) if x_texture_path else '无'}")
    print(f"Y面贴图: {os.path.basename(y_texture_path) if y_texture_path else '无'}")
    print(f"Z面贴图: {os.path.basename(z_texture_path) if z_texture_path else '无'}")
    
    # 如果没有贴图，使用默认材质
    if not x_texture_path and not y_texture_path and not z_texture_path:
        default_mat = create_or_get_default_material(position_id)
        obj.data.materials.append(default_mat)
        
        # 所有面使用默认材质
        for poly in obj.data.polygons:
            poly.material_index = 0
        
        obj.data.update()
        print(f"✓ 已为主模型应用默认材质: {default_mat.name}")
        return True
    
    # 创建或获取共享材质
    x_mat = create_or_get_face_material(position_id, x_texture_path, 'x')
    y_mat = create_or_get_face_material(position_id, y_texture_path, 'y')
    z_mat = create_or_get_face_material(position_id, z_texture_path, 'z')
    
    # 创建或获取默认材质
    default_mat = create_or_get_default_material(position_id)
    
    # 添加材质到对象
    obj.data.materials.append(x_mat)       # 索引0: X面材质
    obj.data.materials.append(y_mat)       # 索引1: Y面材质
    obj.data.materials.append(z_mat)       # 索引2: Z面材质
    obj.data.materials.append(default_mat) # 索引3: 默认材质
    
    # 找到所有方向面
    x_faces, neg_x_faces, y_faces, neg_y_faces, z_faces, neg_z_faces = find_all_directional_faces(obj)
    
    # 检查是否有面
    if len(obj.data.polygons) == 0:
        print(f"警告: 对象 {obj.name} 没有面")
        return False
    
    # 应用材质索引
    x_count = 0
    y_count = 0
    z_count = 0
    default_count = 0
    
    for poly in obj.data.polygons:
        if poly.index in x_faces or poly.index in neg_x_faces:
            poly.material_index = 0      # X面材质
            x_count += 1
        elif poly.index in y_faces or poly.index in neg_y_faces:
            poly.material_index = 1      # Y面材质
            y_count += 1
        elif poly.index in z_faces or poly.index in neg_z_faces:
            poly.material_index = 2      # Z面材质
            z_count += 1
        else:
            poly.material_index = 3      # 默认材质
            default_count += 1
    
    obj.data.update()
    
    print(f"✓ 已应用默认材质系统")
    print(f"  X面材质（索引0）: 应用于 {x_count} 个面（+X和-X）")
    print(f"  Y面材质（索引1）: 应用于 {y_count} 个面（+Y和-Y）")
    print(f"  Z面材质（索引2）: 应用于 {z_count} 个面（+Z和-Z，已应用正确的UV映射）")
    print(f"  默认材质（索引3）: 应用于 {default_count} 个非定向面")
    
    return True

def apply_submodel_materials(obj, position_id, texture_base_path, mapping_data):
    """为子模型应用材质（支持自发光贴图）"""
    print(f"为子模型 {obj.name} 应用材质...")
    
    # 清空现有材质
    if len(obj.data.materials) > 0:
        obj.data.materials.clear()
    
    # 获取子模型名称
    submodel_name = mapping_data.get('submodel_name', '') if mapping_data else ''
    
    # teamspawn类型没有子模型
    if submodel_name and mapping_data.get('blocktype') != 'teamspawn':
        # 查找子模型贴图
        model_config = BlockModelManager().get_model_config(position_id)
        diffuse_texture_path = None
        emission_texture_path = None
        
        if model_config:
            diffuse_texture_path = model_config.get_submodel_texture_path()
            emission_texture_path = model_config.get_submodel_emission_texture_path()
        
        # 创建或获取共享子模型材质（支持自发光贴图）
        submodel_mat = create_or_get_submodel_material(
            position_id, 
            diffuse_texture_path, 
            emission_texture_path, 
            submodel_name,
            emission_strength=2.6
        )
        obj.data.materials.append(submodel_mat)
        
        # 所有面使用子模型材质
        for poly in obj.data.polygons:
            poly.material_index = 0
        
        obj.data.update()
        print(f"✓ 已为子模型应用材质: {submodel_mat.name}")
        print(f"  漫反射贴图: {os.path.basename(diffuse_texture_path) if diffuse_texture_path else '无'}")
        print(f"  自发光贴图: {os.path.basename(emission_texture_path) if emission_texture_path else '无'}")
    else:
        # 使用默认材质
        default_mat = create_or_get_default_material(position_id)
        obj.data.materials.append(default_mat)
        
        for poly in obj.data.polygons:
            poly.material_index = 0
        
        obj.data.update()
        print(f"✓ 已为子模型应用默认材质: {default_mat.name}")
    
    return True

# ============================================================================
# 核心功能函数 - 修复尺寸缩放问题
# ============================================================================

def load_and_setup_model(context, model_path, model_name, position_id, texture_base_path, mapping_data, is_main_model=True):
    """加载并设置模型 - 修复：添加缩放支持"""
    print(f"加载模型: {model_path}")
    
    # 保存当前状态
    current_mode = context.mode
    if current_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    original_selection = list(context.selected_objects)
    original_active = context.active_object
    
    try:
        # 清除所有选择
        bpy.ops.object.select_all(action='DESELECT')
        
        # 检查文件是否存在
        if not os.path.exists(model_path):
            print(f"✗ 模型文件不存在: {model_path}")
            return None
        
        # 获取缩放设置
        settings = context.scene.block_generator_settings
        scale_mode = settings.scale_mode
        custom_scale_factor = settings.custom_scale_factor
        base_block_size = settings.base_block_size
        
        print(f"  缩放设置: 模式={scale_mode}, 自定义缩放={custom_scale_factor}, 基础网格={base_block_size}")
        
        # 导入OBJ文件
        try:
            # 保存当前场景中的所有对象名称
            existing_objects = set(obj.name for obj in bpy.data.objects)
            
            # 导入OBJ
            bpy.ops.wm.obj_import(filepath=model_path)
            
            # 获取导入的新对象
            imported_objs = []
            for obj in bpy.data.objects:
                if obj.name not in existing_objects:
                    imported_objs.append(obj)
            
            if not imported_objs:
                print(f"✗ 没有导入任何网格对象: {model_path}")
                return None
            
            # 合并所有导入的对象（如果有多个）
            if len(imported_objs) > 1:
                for obj in imported_objs:
                    obj.select_set(True)
                context.view_layer.objects.active = imported_objs[0]
                bpy.ops.object.join()
                merged_obj = context.active_object
                merged_obj.name = model_name
            else:
                imported_objs[0].name = model_name
                merged_obj = imported_objs[0]
            
            # 确保在场景中
            if merged_obj.name not in context.collection.objects:
                context.collection.objects.link(merged_obj)
            
            # 选择对象
            bpy.ops.object.select_all(action='DESELECT')
            merged_obj.select_set(True)
            context.view_layer.objects.active = merged_obj
            
            # 应用变换（这会移除缩放，但不应该改变顶点坐标）
            bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
            
            # 移动到原点
            merged_obj.location = (0, 0, 0)
            
            # 计算法线
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
            bpy.ops.mesh.normals_make_consistent(inside=False)
            bpy.ops.object.mode_set(mode='OBJECT')
            
            # 计算原始尺寸
            size_x, size_y, size_z, max_size = calculate_model_dimensions(merged_obj)
            
            # 计算缩放因子
            scale_factor = calculate_scaling_factor(max_size, scale_mode, custom_scale_factor, base_block_size)
            
            # 应用缩放（如果缩放因子不等于1.0）
            if abs(scale_factor - 1.0) > 0.0001:
                print(f"  应用缩放因子: {scale_factor:.6f}")
                merged_obj.scale = (scale_factor, scale_factor, scale_factor)
                bpy.ops.object.transform_apply(scale=True)
                
                # 重新计算缩放后的尺寸
                size_x, size_y, size_z, max_size = calculate_model_dimensions(merged_obj)
            
            # 存储尺寸信息
            merged_obj["block_size_x"] = size_x
            merged_obj["block_size_y"] = size_y
            merged_obj["block_size_z"] = size_z
            merged_obj["block_max_size"] = max_size
            merged_obj["is_main_model"] = is_main_model
            merged_obj["scale_factor"] = scale_factor
            
            print(f"✓ 加载模型成功: {merged_obj.name}")
            print(f"  原始尺寸: X={size_x/scale_factor:.6f}, Y={size_y/scale_factor:.6f}, Z={size_z/scale_factor:.6f}, 最大={max_size/scale_factor:.6f}")
            print(f"  缩放后尺寸: X={size_x:.6f}, Y={size_y:.6f}, Z={size_z:.6f}, 最大={max_size:.6f}")
            print(f"  缩放因子: {scale_factor:.6f}")
            
            # 应用材质
            if is_main_model:
                # 主模型应用根据blocktype的材质系统
                apply_main_model_materials(merged_obj, position_id, texture_base_path, mapping_data)
            else:
                # 子模型应用支持自发光的材质
                apply_submodel_materials(merged_obj, position_id, texture_base_path, mapping_data)
            
            return merged_obj
            
        except Exception as e:
            print(f"✗ 导入模型失败: {e}")
            traceback.print_exc()
            return None
    
    except Exception as e:
        print(f"✗ 加载并设置模型失败: {e}")
        traceback.print_exc()
        return None
    
    finally:
        # 恢复原始选择状态
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in original_selection:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if original_active and original_active.name in bpy.data.objects:
                context.view_layer.objects.active = original_active
        except:
            pass
        
        # 恢复原始模式
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)

def create_template_for_position_id(context, position_id, texture_base_path, models_base_path):
    """为指定位置ID创建模板（支持主模型+子模型系统）- 修复：传递缩放设置"""
    manager = BlockModelManager()
    
    # 检查是否已存在该位置ID的模板
    if manager.has_template_for_id(position_id):
        template = manager.get_template(position_id)
        print(f"位置ID {position_id} 的模板已存在: {template.name}")
        return template
    
    # 获取映射数据
    mapping_data = manager.get_mapping_for_id(position_id)
    
    # 创建模型配置
    model_config = ModelConfig(position_id, mapping_data, texture_base_path, models_base_path)
    manager.set_model_config(position_id, model_config)
    
    print(f"\n为位置ID {position_id} 创建模板...")
    print(f"Blocktype: {mapping_data.get('blocktype') if mapping_data else '无'}")
    print(f"主贴图: {mapping_data.get('main_texture_prefix') if mapping_data else '无'}")
    print(f"子模型: {mapping_data.get('submodel_name') if mapping_data else '无'}")
    print(f"主模型路径: {model_config.main_model_path}")
    print(f"子模型路径: {model_config.submodel_path}")
    print(f"主模型: {'需要' if model_config.has_main_model() else '不需要'}")
    print(f"子模型: {'需要' if model_config.has_submodel() else '不需要'}")
    
    # 保存当前状态
    current_mode = context.mode
    if current_mode != 'OBJECT':
        bpy.ops.object.mode_set(mode='OBJECT')
    
    original_selection = list(context.selected_objects)
    original_active = context.active_object
    
    main_model = None
    submodel = None
    
    try:
        # 清除所有选择
        bpy.ops.object.select_all(action='DESELECT')
        
        # 1. 创建主模型（如果需要）
        if model_config.has_main_model():
            print(f"创建主模型...")
            main_model = load_and_setup_model(
                context,
                model_config.main_model_path,
                f"BlockMain_{position_id}",
                position_id,
                texture_base_path,
                mapping_data,
                is_main_model=True
            )
            if main_model:
                # 隐藏主模型
                main_model.hide_set(True)
                main_model.hide_render = True
                print(f"✓ 主模型创建成功: {main_model.name}")
            else:
                print(f"✗ 主模型创建失败")
        
        # 2. 创建子模型（如果需要）
        if model_config.has_submodel():
            print(f"创建子模型...")
            submodel = load_and_setup_model(
                context,
                model_config.submodel_path,
                f"BlockSub_{position_id}",
                position_id,
                texture_base_path,
                mapping_data,
                is_main_model=False
            )
            if submodel:
                # 隐藏子模型
                submodel.hide_set(True)
                submodel.hide_render = True
                print(f"✓ 子模型创建成功: {submodel.name}")
            else:
                print(f"✗ 子模型创建失败")
        
        # 3. 创建容器组（用于模板）
        if main_model or submodel:
            # 创建空对象作为容器
            container = bpy.data.objects.new(f"BlockTemplate_{position_id}", None)
            context.collection.objects.link(container)
            
            # 设置容器位置为原点
            container.location = (0, 0, 0)
            
            # 将主模型和子模型设置为容器的子对象
            if main_model:
                main_model.parent = container
                main_matrix = main_model.matrix_world.copy()
                main_model.matrix_parent_inverse = container.matrix_world.inverted() @ main_matrix
            
            if submodel:
                submodel.parent = container  # 子模型直接挂载到模板容器
                sub_matrix = submodel.matrix_world.copy()
                submodel.matrix_parent_inverse = container.matrix_world.inverted() @ sub_matrix
            
            # 隐藏模板容器
            container.hide_set(True)
            container.hide_render = True
            
            # 保存模板
            manager.set_template(position_id, container)
            
            print(f"✓ 成功创建位置ID {position_id} 的模板容器: {container.name}")
            if main_model:
                print(f"  包含主模型: {main_model.name}")
            if submodel:
                print(f"  包含子模型: {submodel.name}")
            return container
        
        else:
            print(f"✗ 位置ID {position_id} 没有可创建的模型")
            return None
        
    except Exception as e:
        print(f"✗ 创建位置ID {position_id} 的模板失败: {e}")
        import traceback
        traceback.print_exc()
        
        # 清理创建的对象
        if main_model and main_model.name in bpy.data.objects:
            bpy.data.objects.remove(main_model)
        if submodel and submodel.name in bpy.data.objects:
            bpy.data.objects.remove(submodel)
        
        return None
    
    finally:
        # 恢复原始选择状态
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in original_selection:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if original_active and original_active.name in bpy.data.objects:
                context.view_layer.objects.active = original_active
        except:
            pass
        
        # 恢复原始模式
        if current_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=current_mode)

def create_block_from_template(context, position_id, x, y, z, base_block_size, 
                              direction_mode='EAST', use_model_center=False):
    """从模板创建方块（支持主模型+子模型系统）"""
    print(f"\n创建方块: 位置ID={position_id}, 坐标=({x},{y},{z}), 方向={direction_mode}")
    
    block_name = f"Block_{position_id}_{x}_{y}_{z}"
    
    # 检查是否已存在
    if block_name in bpy.data.objects:
        print(f"方块已存在: {block_name}")
        return bpy.data.objects[block_name]
    
    # 获取位置ID对应的模板容器
    manager = BlockModelManager()
    template_container = manager.get_template(position_id)
    
    if not template_container:
        print(f"✗ 错误: 找不到位置ID {position_id} 的模板")
        return None
    
    # 获取模板尺寸（使用第一个子对象的尺寸）
    container_children = [child for child in template_container.children]
    if not container_children:
        print(f"✗ 错误: 模板容器没有子对象")
        return None
    
    # 使用第一个子对象的尺寸
    child_obj = container_children[0]
    if "block_size_x" in child_obj:
        size_x = child_obj["block_size_x"]
        size_y = child_obj["block_size_y"]
        size_z = child_obj["block_size_z"]
    else:
        # 重新计算尺寸
        size_x, size_y, size_z, _ = calculate_model_dimensions(child_obj)
    
    print(f"模型尺寸: X={size_x:.6f}, Y={size_y:.6f}, Z={size_z:.6f}")
    print(f"基础网格大小: {base_block_size}")
    
    # 获取设置以确定是否使用相邻模式
    settings = context.scene.block_generator_settings
    adjacent_mode = settings.adjacent_mode
    
    # 根据模型尺寸和基础网格大小计算世界坐标
    world_x, world_y, world_z = get_world_coordinate_for_model(
        (x, y, z), base_block_size, size_x, size_y, size_z,
        direction_mode, use_model_center, adjacent_mode
    )
    
    # 获取旋转角度
    rotation_y = get_rotation_for_direction(direction_mode)
    
    original_selection = list(context.selected_objects)
    original_active = context.active_object
    
    try:
        # 清除所有选择
        bpy.ops.object.select_all(action='DESELECT')
        
        # 复制模板容器及其所有子对象
        print(f"复制模板容器: {template_container.name}")
        
        # 先显示模板容器及其子对象
        template_container.hide_set(False)
        for child in template_container.children:
            child.hide_set(False)
        
        # 选择模板容器及其所有子对象
        template_container.select_set(True)
        for child in template_container.children:
            child.select_set(True)
        
        context.view_layer.objects.active = template_container
        
        # 复制选中的对象
        bpy.ops.object.duplicate()
        
        # 获取复制的容器
        duplicated_objs = [obj for obj in context.selected_objects]
        new_container = None
        
        # 查找复制的容器（EMPTY类型）
        for obj in duplicated_objs:
            if obj.type == 'EMPTY' and obj.name.startswith(f"{template_container.name}."):
                new_container = obj
                new_container.name = block_name
                break
        
        if not new_container:
            # 如果没有找到空的容器对象，创建一个新的空对象作为容器
            new_container = bpy.data.objects.new(block_name, None)
            context.collection.objects.link(new_container)
            
            # 将复制的对象设置为新容器的子对象
            for obj in duplicated_objs:
                if obj != new_container:
                    obj.parent = new_container
                    obj.matrix_parent_inverse = new_container.matrix_world.inverted() @ obj.matrix_world.copy()
        
        # 设置新容器的位置和旋转
        # 不使用四舍五入，保持原始精度
        new_container.location = (world_x, world_y, world_z)
        new_container.rotation_euler = (0.0, rotation_y, 0.0)
        
        # 存储信息
        new_container["grid_x"] = x
        new_container["grid_y"] = y
        new_container["grid_z"] = z
        new_container["position_id"] = position_id
        new_container["direction"] = direction_mode
        
        # 重命名子对象
        for child in new_container.children:
            if child.name.startswith("BlockMain_"):
                child.name = f"BlockMain_{position_id}_{x}_{y}_{z}"
            elif child.name.startswith("BlockSub_"):
                child.name = f"BlockSub_{position_id}_{x}_{y}_{z}"
        
        # 重新隐藏模板容器及其子对象
        template_container.hide_set(True)
        for child in template_container.children:
            child.hide_set(True)
        
        print(f"✓ 成功创建方块容器: {new_container.name}")
        print(f"位置: ({world_x:.6f}, {world_y:.6f}, {world_z:.6f})")
        print(f"旋转: {rotation_y:.6f} 弧度 ({direction_mode}方向)")
        print(f"包含 {len(new_container.children)} 个子对象:")
        for child in new_container.children:
            print(f"  - {child.name} ({child.type})")
        
        return new_container
        
    except Exception as e:
        print(f"✗ 创建方块时出错: {e}")
        import traceback
        traceback.print_exc()
        
        # 确保模板容器被重新隐藏
        if template_container:
            template_container.hide_set(True)
            for child in template_container.children:
                child.hide_set(True)
        
        return None
    
    finally:
        # 恢复原始选择状态
        try:
            bpy.ops.object.select_all(action='DESELECT')
            for obj in original_selection:
                if obj and obj.name in bpy.data.objects:
                    obj.select_set(True)
            if original_active and original_active.name in bpy.data.objects:
                context.view_layer.objects.active = original_active
        except:
            pass

# ============================================================================
# 属性组定义
# ============================================================================

class BlockModelItem(bpy.types.PropertyGroup):
    """存储方块模型信息的属性组"""
    id: bpy.props.IntProperty(name="ID", min=0, max=999)
    name: bpy.props.StringProperty(name="名称")
    filepath: bpy.props.StringProperty(name="文件路径", subtype='FILE_PATH')
    color: bpy.props.FloatVectorProperty(
        name="颜色",
        subtype='COLOR',
        default=(0.8, 0.4, 0.1),
        min=0.0,
        max=1.0
    )
    is_loaded: bpy.props.BoolProperty(name="已加载", default=False)
    # 添加原始尺寸记录
    original_size_x: bpy.props.FloatProperty(name="原始X尺寸", default=1.0)
    original_size_y: bpy.props.FloatProperty(name="原始Y尺寸", default=1.0)
    original_size_z: bpy.props.FloatProperty(name="原始Z尺寸", default=1.0)
    original_max_size: bpy.props.FloatProperty(name="原始最大尺寸", default=1.0)
    # 添加缩放因子
    scale_factor: bpy.props.FloatProperty(name="缩放因子", default=1.0, min=0.001, max=100.0)

class BlockGeneratorSettings(bpy.types.PropertyGroup):
    """方块生成器的设置"""
    
    # 比例模式枚举
    scale_mode_items = [
        ('ORIGINAL', "保持原始比例", "保持模型导入时的原始尺寸"),
        ('ONE_METER', "缩放到1米", "强制将模型缩放到1米大小"),
        ('CUSTOM', "自定义比例", "使用自定义缩放因子"),
    ]
    
    scale_mode: bpy.props.EnumProperty(
        name="缩放模式",
        description="选择模型的缩放方式",
        items=scale_mode_items,
        default='ONE_METER'
    )
    
    custom_scale_factor: bpy.props.FloatProperty(
        name="自定义缩放",
        description="自定义缩放因子",
        default=1.0,
        min=0.001,
        max=1000.0,
        step=0.1,
        precision=3
    )
    
    base_block_size: bpy.props.FloatProperty(
        name="基础网格大小",
        default=1.0,
        min=0.1,
        max=10.0,
        description="基础网格单位大小，模型尺寸会在此基础上调整",
        subtype='DISTANCE'
    )
    
    # 方向模式枚举
    direction_mode_items = [
        ('EAST', "朝东", "方块朝向东方（+X方向）"),
        ('SOUTH', "朝南", "方块朝向南方（-Z方向）"),
        ('WEST', "朝西", "方块朝向西方（-X方向）"),
        ('NORTH', "朝北", "方块朝向北方（+Z方向）"),
    ]
    
    direction_mode: bpy.props.EnumProperty(
        name="方块方向",
        description="选择方块的朝向",
        items=direction_mode_items,
        default='EAST'
    )
    
    # 定位选项
    positioning_mode_items = [
        ('MODEL_CENTER', "模型中心", "使用模型中心作为定位点"),
        ('MODEL_BASE', "模型底部", "使用模型底部作为定位点"),
    ]
    
    positioning_mode: bpy.props.EnumProperty(
        name="定位模式",
        description="选择方块的定位方式",
        items=positioning_mode_items,
        default='MODEL_BASE'
    )
    
    # 相邻模式
    adjacent_mode: bpy.props.BoolProperty(
        name="启用相邻模式",
        description="使相邻坐标的方块紧密相邻，根据模型大小调整位置",
        default=True  # 默认启用相邻模式
    )
    
    # 自发光强度设置
    emission_strength: bpy.props.FloatProperty(
        name="自发光强度",
        description="自发光贴图的发光强度",
        default=2.6,
        min=0.0,
        max=100.0,
        step=0.1,
        precision=2
    )

# ============================================================================
# 操作符类
# ============================================================================

class OBJECT_OT_load_block_models(bpy.types.Operator):
    bl_idname = "object.load_block_models"
    bl_label = "选择模型文件夹"
    bl_description = "选择包含OBJ方块模型的文件夹"
    
    directory: bpy.props.StringProperty(
        name="模型文件夹",
        description="包含OBJ文件的文件夹路径",
        subtype='DIR_PATH'
    )
    
    filter_glob: bpy.props.StringProperty(
        default="",  # 清空过滤，允许选择文件夹
        options={'HIDDEN'}
    )
    
    def execute(self, context):
        scene = context.scene
        
        if not self.directory:
            self.report({'WARNING'}, "请选择文件夹")
            return {'CANCELLED'}
        
        print(f"\n正在扫描模型文件夹: {self.directory}")
        
        # 清空现有模型列表
        scene.block_models.clear()
        
        # 扫描文件夹中的OBJ文件
        loaded_count = 0
        
        # 首先检查是否存在block.obj文件（主模型）
        block_obj_path = os.path.join(self.directory, "block.obj")
        if os.path.exists(block_obj_path):
            # 添加主模型
            item = scene.block_models.add()
            item.id = 0
            item.name = "block"
            item.filepath = block_obj_path
            item.color = (0.8, 0.4, 0.1)
            item.scale_factor = 1.0
            loaded_count += 1
            print(f"✓ 找到主模型: block.obj")
        
        # 扫描所有OBJ文件
        for filename in os.listdir(self.directory):
            if filename.lower().endswith('.obj'):
                # 跳过已经添加的block.obj
                if filename.lower() == 'block.obj':
                    continue
                
                base_name = os.path.splitext(filename)[0]
                block_id = 0
                
                # 尝试从文件名提取ID
                numbers = re.findall(r'\d+', base_name)
                if numbers:
                    block_id = int(numbers[0])
                else:
                    # 如果文件名没有数字，使用加载顺序+1（避免与block.obj的ID 0冲突）
                    block_id = loaded_count + 1
                
                filepath = os.path.join(self.directory, filename)
                
                # 添加到模型列表
                item = scene.block_models.add()
                item.id = block_id
                item.name = base_name
                item.filepath = filepath
                item.color = (0.8, 0.4, 0.1)
                item.scale_factor = 1.0
                
                loaded_count += 1
                print(f"✓ 找到模型: {filename} (ID: {block_id})")
        
        if loaded_count > 0:
            # 按ID排序
            scene.block_models.sort(key=lambda x: x.id)
            self.report({'INFO'}, f"已找到 {loaded_count} 个OBJ模型")
            print(f"总计找到 {loaded_count} 个模型文件")
        else:
            self.report({'WARNING'}, "文件夹中没有找到OBJ文件")
            print(f"✗ 未找到OBJ文件")
        
        return {'FINISHED'}
    
    def invoke(self, context, event):
        # 设置默认目录（如果之前设置过贴图路径，则使用其父目录）
        scene = context.scene
        if scene.texture_base_path:
            # 尝试使用贴图路径的父目录作为默认目录
            default_dir = os.path.dirname(scene.texture_base_path.rstrip('/\\'))
            if os.path.exists(default_dir):
                self.directory = default_dir
        
        # 打开文件夹选择器
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class OBJECT_OT_set_texture_base_path(bpy.types.Operator):
    bl_idname = "object.set_texture_base_path"
    bl_label = "设置贴图基础路径"
    bl_description = "设置贴图文件的基础路径"
    
    directory: bpy.props.StringProperty(
        name="贴图基础路径",
        subtype='DIR_PATH'
    )
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        scene = context.scene
        
        if not self.directory:
            self.report({'WARNING'}, "请选择文件夹")
            return {'CANCELLED'}
        
        if not os.path.isdir(self.directory):
            self.report({'ERROR'}, f"目录不存在: {self.directory}")
            return {'CANCELLED'}
        
        scene.texture_base_path = self.directory
        self.report({'INFO'}, f"贴图基础路径已设置为: {self.directory}")
        
        return {'FINISHED'}

class OBJECT_OT_set_models_base_path(bpy.types.Operator):
    bl_idname = "object.set_models_base_path"
    bl_label = "设置模型基础路径"
    bl_description = "设置模型文件的基础路径"
    
    directory: bpy.props.StringProperty(
        name="模型基础路径",
        subtype='DIR_PATH'
    )
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}
    
    def execute(self, context):
        scene = context.scene
        
        if not self.directory:
            self.report({'WARNING'}, "请选择文件夹")
            return {'CANCELLED'}
        
        if not os.path.isdir(self.directory):
            self.report({'ERROR'}, f"目录不存在: {self.directory}")
            return {'CANCELLED'}
        
        scene.models_base_path = self.directory
        self.report({'INFO'}, f"模型基础路径已设置为: {self.directory}")
        
        return {'FINISHED'}

class OBJECT_OT_load_mapping_table(bpy.types.Operator):
    bl_idname = "object.load_mapping_table"
    bl_label = "加载映射表"
    bl_description = "加载映射表文件（ta.txt）"
    
    filepath: bpy.props.StringProperty(
        name="映射表文件",
        subtype='FILE_PATH'
    )
    
    filter_glob: bpy.props.StringProperty(
        default="*.txt;*.csv;*.dat",
        options={'HIDDEN'}
    )
    
    def execute(self, context):
        scene = context.scene
        
        try:
            # 加载映射表
            manager = BlockModelManager()
            manager.set_mapping_table(self.filepath)
            
            scene.mapping_table_path = self.filepath
            mapping_count = manager.get_mapping_count()
            self.report({'INFO'}, f"已加载映射表，共 {mapping_count} 个条目")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"加载映射表失败: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class OBJECT_OT_reload_mapping_table(bpy.types.Operator):
    bl_idname = "object.reload_mapping_table"
    bl_label = "重新加载映射表"
    bl_description = "重新加载当前设置的映射表文件"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        if not scene.mapping_table_path:
            self.report({'WARNING'}, "没有设置映射表路径")
            return {'CANCELLED'}
        
        if not os.path.exists(scene.mapping_table_path):
            self.report({'ERROR'}, f"映射表文件不存在: {scene.mapping_table_path}")
            return {'CANCELLED'}
        
        try:
            # 重新加载映射表
            manager = BlockModelManager()
            success = manager.reload_mapping_table(scene)
            
            if success:
                mapping_count = manager.get_mapping_count()
                self.report({'INFO'}, f"已重新加载映射表，共 {mapping_count} 个条目")
            else:
                self.report({'ERROR'}, f"重新加载映射表失败")
            
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"重新加载映射表失败: {str(e)}")
            return {'CANCELLED'}

class OBJECT_OT_import_positions(bpy.types.Operator):
    bl_idname = "object.import_positions"
    bl_label = "导入位置信息"
    bl_description = "从文本文件导入方块位置信息"
    
    filepath: bpy.props.StringProperty(
        name="文件路径",
        subtype='FILE_PATH'
    )
    
    filter_glob: bpy.props.StringProperty(
        default="*.txt;*.csv;*.dat;*",
        options={'HIDDEN'}
    )
    
    def execute(self, context):
        scene = context.scene
        
        try:
            # 读取文件内容
            with open(self.filepath, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # 直接使用文件内容
            scene.grid_coordinates = content
            
            # 解析坐标以显示统计信息
            coordinates = parse_coordinate_string(content)
            
            self.report({'INFO'}, f"已导入 {len(coordinates)} 个位置信息")
            return {'FINISHED'}
            
        except Exception as e:
            self.report({'ERROR'}, f"导入失败: {str(e)}")
            return {'CANCELLED'}
    
    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

class OBJECT_OT_generate_from_grid(bpy.types.Operator):
    bl_idname = "object.generate_from_grid"
    bl_label = "从坐标生成方块"
    bl_description = "根据坐标生成方块，支持主模型+子模型系统，支持自发光贴图，修复尺寸缩放问题"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        if not scene.grid_coordinates.strip():
            self.report({'WARNING'}, "请输入坐标")
            return {'CANCELLED'}
        
        coordinates = parse_coordinate_string(scene.grid_coordinates)
        
        if not coordinates:
            self.report({'WARNING'}, "没有找到有效的坐标")
            return {'CANCELLED'}
        
        settings = scene.block_generator_settings
        base_block_size = settings.base_block_size
        
        # 检查必要的路径
        if not scene.models_base_path:
            self.report({'ERROR'}, "请先设置模型基础路径")
            return {'CANCELLED'}
        
        if not scene.texture_base_path:
            self.report({'ERROR'}, "请先设置贴图基础路径")
            return {'CANCELLED'}
        
        # 获取管理器实例
        manager = BlockModelManager()
        
        # 修复：检查并重新加载映射表
        if not manager._mapping_table and scene.mapping_table_path:
            print(f"重新加载映射表: {scene.mapping_table_path}")
            manager.set_mapping_table(scene.mapping_table_path)
        
        if not manager._mapping_table:
            self.report({'WARNING'}, "没有加载映射表，将使用默认配置")
        
        print(f"\n{'='*60}")
        print(f"开始生成 {len(coordinates)} 个方块")
        print(f"贴图基础路径: {scene.texture_base_path}")
        print(f"模型基础路径: {scene.models_base_path}")
        print(f"基础网格大小: {base_block_size}")
        print(f"方块方向: {settings.direction_mode}")
        print(f"定位模式: {settings.positioning_mode}")
        print(f"相邻模式: {'启用' if settings.adjacent_mode else '禁用'}")
        print(f"缩放模式: {settings.scale_mode}")
        if settings.scale_mode == 'CUSTOM':
            print(f"自定义缩放因子: {settings.custom_scale_factor}")
        print(f"自发光强度: {settings.emission_strength}")
        print(f"映射表条目数: {manager.get_mapping_count()}")
        
        # 统计所需的位置ID
        required_ids = set(coord['id'] for coord in coordinates)
        print(f"位置表中需要的位置ID列表: {sorted(required_ids)}")
        
        # 为每个位置ID创建模板（支持主模型+子模型系统）
        print(f"\n为每个位置ID创建模板（支持主模型+子模型系统）...")
        templates_created = 0
        for position_id in required_ids:
            template = create_template_for_position_id(
                context, 
                position_id, 
                scene.texture_base_path,
                scene.models_base_path
            )
            if template:
                templates_created += 1
                print(f"✓ 创建位置ID {position_id} 的模板成功: {template.name}")
            else:
                print(f"✗ 创建位置ID {position_id} 的模板失败")
        
        if templates_created == 0:
            self.report({'ERROR'}, "没有成功创建任何模板")
            return {'CANCELLED'}
        
        print(f"总计为 {len(required_ids)} 个位置ID创建了 {templates_created} 个模板")
        
        # 生成方块
        generated_count = 0
        failed_count = 0
        
        # 确定定位模式
        use_model_center = (settings.positioning_mode == 'MODEL_CENTER')
        
        for i, coord in enumerate(coordinates):
            position_id = coord['id']
            x = coord['x']
            y = coord['y']
            z = coord['z']
            
            print(f"\n生成方块 {i+1}/{len(coordinates)}: 位置ID={position_id}, 坐标=({x},{y},{z})")
            
            block = create_block_from_template(
                context, 
                position_id, 
                x, y, z, 
                base_block_size,
                settings.direction_mode,
                use_model_center
            )
            
            if block:
                generated_count += 1
                print(f"✓ 成功生成方块 {generated_count}")
            else:
                failed_count += 1
                print(f"✗ 生成方块失败: 位置ID={position_id}")
        
        print(f"\n{'='*60}")
        print(f"生成完成:")
        print(f"成功: {generated_count} 个")
        print(f"失败: {failed_count} 个")
        
        if generated_count > 0:
            self.report({'INFO'}, f"成功生成 {generated_count} 个方块，失败 {failed_count} 个")
        else:
            self.report({'WARNING'}, "没有成功生成任何方块")
        
        return {'FINISHED'}

class OBJECT_OT_clear_all_blocks(bpy.types.Operator):
    bl_idname = "object.clear_all_blocks"
    bl_label = "清空所有方块"
    bl_description = "删除场景中的所有生成方块"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        blocks_removed = 0
        
        blocks_to_remove = []
        for obj in bpy.data.objects:
            if obj.name.startswith("Block_") and not obj.name.startswith("BlockTemplate_"):
                blocks_to_remove.append(obj)
        
        for obj in blocks_to_remove:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                blocks_removed += 1
            except:
                pass
        
        self.report({'INFO'}, f"已删除 {blocks_removed} 个方块")
        return {'FINISHED'}

class OBJECT_OT_clear_all_templates(bpy.types.Operator):
    bl_idname = "object.clear_all_templates"
    bl_label = "清除所有模板"
    bl_description = "清除所有模板模型和材质，但保留映射表和路径设置"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        # 获取管理器
        manager = BlockModelManager()
        
        # 只清除模板和模型配置，保留映射表
        manager.clear_templates_and_configs()
        
        # 删除模板对象
        templates_removed = 0
        templates_to_remove = []
        for obj in bpy.data.objects:
            if obj.name.startswith("BlockTemplate_") or obj.name.startswith("BlockMain_") or obj.name.startswith("BlockSub_"):
                templates_to_remove.append(obj)
        
        for obj in templates_to_remove:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                templates_removed += 1
            except:
                pass
        
        # 清理未使用的材质（只清理用户数为0的材质）
        materials_removed = 0
        materials_to_remove = []
        for mat in bpy.data.materials:
            if mat.name.startswith("BlockMat_") and mat.users == 0:
                materials_to_remove.append(mat)
        
        for mat in materials_to_remove:
            try:
                bpy.data.materials.remove(mat)
                materials_removed += 1
            except:
                pass
        
        # 清理管理器中的材质缓存
        manager._materials.clear()
        manager._loaded_textures.clear()
        
        self.report({'INFO'}, f"已清除 {templates_removed} 个模板模型和 {materials_removed} 个未使用的材质")
        return {'FINISHED'}

class OBJECT_OT_clear_all_templates_and_mapping(bpy.types.Operator):
    bl_idname = "object.clear_all_templates_and_mapping"
    bl_label = "清除所有（包括映射表）"
    bl_description = "清除所有模板模型、材质和映射表"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        # 获取管理器
        manager = BlockModelManager()
        
        # 清除所有数据（包括映射表）
        manager.clear_all()
        
        # 删除模板对象
        templates_removed = 0
        templates_to_remove = []
        for obj in bpy.data.objects:
            if obj.name.startswith("BlockTemplate_") or obj.name.startswith("BlockMain_") or obj.name.startswith("BlockSub_"):
                templates_to_remove.append(obj)
        
        for obj in templates_to_remove:
            try:
                bpy.data.objects.remove(obj, do_unlink=True)
                templates_removed += 1
            except:
                pass
        
        # 清理未使用的材质
        materials_removed = 0
        for mat in list(bpy.data.materials):
            if mat.name.startswith("BlockMat_") and mat.users == 0:
                try:
                    bpy.data.materials.remove(mat)
                    materials_removed += 1
                except:
                    pass
        
        # 清空映射表路径
        scene.mapping_table_path = ""
        
        self.report({'INFO'}, f"已清除 {templates_removed} 个模板模型和 {materials_removed} 个未使用的材质，并清空映射表")
        return {'FINISHED'}

class OBJECT_OT_debug_position_calculation(bpy.types.Operator):
    bl_idname = "object.debug_position_calculation"
    bl_label = "调试位置计算"
    bl_description = "调试世界坐标计算函数，查看具体计算过程"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        settings = scene.block_generator_settings
        
        # 获取一个测试坐标
        test_coords = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, 0, 1), (-1, 0, 1), (1, 1, 1)]
        
        # 如果没有模板，使用默认尺寸
        size_x, size_y, size_z = 1.0, 1.0, 1.0
        
        print(f"\n{'='*60}")
        print(f"调试位置计算:")
        print(f"基础网格大小: {settings.base_block_size}")
        print(f"模型尺寸: X={size_x:.3f}, Y={size_y:.3f}, Z={size_z:.3f}")
        print(f"方向: {settings.direction_mode}")
        print(f"定位模式: {settings.positioning_mode}")
        print(f"相邻模式: {'启用' if settings.adjacent_mode else '禁用'}")
        
        use_model_center = (settings.positioning_mode == 'MODEL_CENTER')
        
        for i, (x, y, z) in enumerate(test_coords):
            world_x, world_y, world_z = get_world_coordinate_for_model(
                (x, y, z), settings.base_block_size, size_x, size_y, size_z,
                settings.direction_mode, use_model_center, settings.adjacent_mode
            )
            
            print(f"  网格({x},{y},{z}) -> 世界({world_x:.3f},{world_y:.3f},{world_z:.3f})")
            
            # 如果是垂直方向，显示高度信息
            if z > 0:
                prev_x, prev_y, prev_z = get_world_coordinate_for_model(
                    (x, y, z-1), settings.base_block_size, size_x, size_y, size_z,
                    settings.direction_mode, use_model_center, settings.adjacent_mode
                )
                height_diff = world_z - prev_z
                print(f"      Z轴相邻: 底部在 {prev_z:.3f}, 当前在 {world_z:.3f}, 高度差: {height_diff:.3f} (期望: {size_z:.3f})")
        
        self.report({'INFO'}, "位置计算调试完成，查看控制台输出")
        return {'FINISHED'}

class OBJECT_OT_test_mapping_system(bpy.types.Operator):
    bl_idname = "object.test_mapping_system"
    bl_label = "测试映射系统"
    bl_description = "测试映射表驱动的模型加载系统，包括自发光贴图"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        
        print(f"\n{'='*60}")
        print(f"测试映射系统")
        
        # 检查必要的路径
        if not scene.models_base_path:
            self.report({'ERROR'}, "请先设置模型基础路径")
            return {'CANCELLED'}
        
        if not scene.texture_base_path:
            self.report({'ERROR'}, "请先设置贴图基础路径")
            return {'CANCELLED'}
        
        # 检查映射表
        manager = BlockModelManager()
        
        # 修复：检查并重新加载映射表
        if not manager._mapping_table and scene.mapping_table_path:
            print(f"重新加载映射表: {scene.mapping_table_path}")
            manager.set_mapping_table(scene.mapping_table_path)
        
        if not manager._mapping_table:
            self.report({'WARNING'}, "没有加载映射表，将无法测试映射系统")
            return {'CANCELLED'}
        
        # 测试几个ID
        test_ids = list(manager._mapping_table.keys())[:5]  # 测试前5个ID
        
        print(f"测试 {len(test_ids)} 个ID: {test_ids}")
        
        for position_id in test_ids:
            mapping_data = manager.get_mapping_for_id(position_id)
            print(f"\n测试位置ID {position_id}:")
            print(f"  Blocktype: {mapping_data.get('blocktype')}")
            print(f"  主贴图前缀: {mapping_data.get('main_texture_prefix')}")
            print(f"  子模型名称: {mapping_data.get('submodel_name')}")
            print(f"  Z面贴图前缀: {mapping_data.get('z_texture_prefix')}")
            
            # 创建模型配置
            model_config = ModelConfig(position_id, mapping_data, scene.texture_base_path, scene.models_base_path)
            
            print(f"  主模型: {'需要' if model_config.has_main_model() else '不需要'}")
            print(f"  子模型: {'需要' if model_config.has_submodel() else '不需要'}")
            
            # 测试贴图查找
            if mapping_data.get('main_texture_prefix'):
                for face_type in ['x', 'y', 'z']:
                    tex_path = model_config.get_texture_path(face_type)
                    print(f"  {face_type}面贴图: {'找到' if tex_path else '未找到'}")
            
            if mapping_data.get('submodel_name'):
                diffuse_tex_path = model_config.get_submodel_texture_path()
                emission_tex_path = model_config.get_submodel_emission_texture_path()
                print(f"  子模型漫反射贴图: {'找到' if diffuse_tex_path else '未找到'}")
                print(f"  子模型自发光贴图: {'找到' if emission_tex_path else '未找到'}")
        
        # 测试创建模板
        print(f"\n测试创建模板...")
        for position_id in test_ids[:3]:  # 测试前3个ID的模板创建
            print(f"\n为位置ID {position_id} 创建模板:")
            template = create_template_for_position_id(
                context,
                position_id,
                scene.texture_base_path,
                scene.models_base_path
            )
            
            if template:
                print(f"✓ 模板创建成功: {template.name}")
                print(f"  包含 {len(template.children)} 个子对象")
                for child in template.children:
                    print(f"    - {child.name} ({child.type})")
            else:
                print(f"✗ 模板创建失败")
        
        self.report({'INFO'}, "映射系统测试完成，查看控制台输出")
        return {'FINISHED'}

class OBJECT_OT_test_submodel_emission_material(bpy.types.Operator):
    bl_idname = "object.test_submodel_emission_material"
    bl_label = "测试子模型自发光材质"
    bl_description = "创建一个测试子模型自发光材质的方块"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        scene = context.scene
        settings = scene.block_generator_settings
        
        print(f"\n{'='*60}")
        print(f"测试子模型自发光材质")
        
        # 检查必要的路径
        if not scene.models_base_path:
            self.report({'ERROR'}, "请先设置模型基础路径")
            return {'CANCELLED'}
        
        if not scene.texture_base_path:
            self.report({'ERROR'}, "请先设置贴图基础路径")
            return {'CANCELLED'}
        
        # 创建一个测试方块
        test_position_id = 999  # 使用一个特殊的ID
        test_x, test_y, test_z = 0, 0, 0
        
        # 创建模拟的映射数据
        test_mapping_data = {
            'position_id': test_position_id,
            'blocktype': 'minestone',
            'main_texture_prefix': '',  # 没有主贴图
            'submodel_name': 'test_mushroom',  # 测试子模型
            'z_texture_prefix': '',
            'has_main_texture': False,
            'has_submodel': True,
            'has_z_texture': False,
        }
        
        # 设置映射数据
        manager = BlockModelManager()
        manager._mapping_table[test_position_id] = test_mapping_data
        
        # 创建模型配置
        model_config = ModelConfig(test_position_id, test_mapping_data, scene.texture_base_path, scene.models_base_path)
        manager.set_model_config(test_position_id, model_config)
        
        # 检查贴图路径
        print(f"测试子模型贴图:")
        print(f"  漫反射贴图路径: {model_config.get_submodel_texture_path()}")
        print(f"  自发光贴图路径: {model_config.get_submodel_emission_texture_path()}")
        
        # 创建测试材质
        print(f"\n创建测试材质...")
        test_material = create_or_get_submodel_material(
            test_position_id,
            model_config.get_submodel_texture_path(),
            model_config.get_submodel_emission_texture_path(),
            'test_mushroom',
            settings.emission_strength
        )
        
        if test_material:
            print(f"✓ 测试材质创建成功: {test_material.name}")
            
            # 打开节点编辑器查看材质
            for area in context.screen.areas:
                if area.type == 'NODE_EDITOR':
                    area.spaces.active.node_tree = test_material.node_tree
                    break
            
            # 创建一个简单的立方体来应用材质
            bpy.ops.mesh.primitive_cube_add(size=1, location=(0, 0, 2))
            cube = context.active_object
            cube.name = f"Test_Submodel_Emission_{test_position_id}"
            
            # 清空现有材质并添加测试材质
            if len(cube.data.materials) > 0:
                cube.data.materials.clear()
            cube.data.materials.append(test_material)
            
            # 选择对象
            cube.select_set(True)
            context.view_layer.objects.active = cube
            
            self.report({'INFO'}, f"已创建测试子模型自发光材质: {test_material.name}")
        else:
            print(f"✗ 测试材质创建失败")
            self.report({'ERROR'}, "测试材质创建失败")
        
        return {'FINISHED'}

class OBJECT_OT_cleanup_duplicate_materials(bpy.types.Operator):
    bl_idname = "object.cleanup_duplicate_materials"
    bl_label = "清理重复材质"
    bl_description = "清理重复的方块材质"
    bl_options = {'REGISTER', 'UNDO'}
    
    def execute(self, context):
        manager = BlockModelManager()
        duplicates = manager.clear_duplicate_materials()
        
        self.report({'INFO'}, f"清理了 {len(duplicates)} 个重复材质")
        return {'FINISHED'}

# ============================================================================
# 面板类
# ============================================================================

class VIEW3D_PT_block_generator_main(bpy.types.Panel):
    bl_label = "方块网格生成器增强版"
    bl_idname = "VIEW3D_PT_block_generator_main"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "方块工具"
    
    def draw(self, context):
        layout = self.layout
        scene = context.scene
        settings = scene.block_generator_settings
        
        # 映射表设置
        box = layout.box()
        box.label(text="映射表设置", icon='FILE_TEXT')
        
        col = box.column(align=True)
        row = col.row(align=True)
        row.operator("object.load_mapping_table", text="加载映射表", icon='FILEBROWSER')
        row.operator("object.reload_mapping_table", text="重新加载", icon='FILE_REFRESH')
        
        if scene.mapping_table_path:
            col.label(text=f"当前映射表: {scene.mapping_table_path}", icon='INFO')
            
            # 显示映射表统计
            manager = BlockModelManager()
            mapping_count = manager.get_mapping_count()
            
            # 修复：如果映射表为空但路径存在，尝试重新加载
            if mapping_count == 0 and scene.mapping_table_path and os.path.exists(scene.mapping_table_path):
                col.label(text="映射表文件存在但未加载，点击'重新加载'重新加载", icon='ERROR')
            elif mapping_count > 0:
                col.label(text=f"已加载 {mapping_count} 个映射条目", icon='INFO')
            else:
                col.label(text="未加载映射表", icon='ERROR')
        
        # 路径设置
        box = layout.box()
        box.label(text="路径设置", icon='FILE_FOLDER')
        
        col = box.column(align=True)
        col.operator("object.set_models_base_path", text="设置模型基础路径", icon='FILEBROWSER')
        col.operator("object.set_texture_base_path", text="设置贴图基础路径", icon='FILEBROWSER')
        
        if scene.models_base_path:
            col.label(text=f"模型路径: {scene.models_base_path}", icon='INFO')
            
            # 检查路径是否存在
            if os.path.exists(scene.models_base_path):
                col.label(text="✓ 路径存在", icon='CHECKMARK')
                
                # 检查是否有models文件夹
                models_folder = os.path.join(scene.models_base_path, "models")
                if os.path.exists(models_folder):
                    col.label(text="✓ models文件夹存在", icon='CHECKMARK')
                    
                    # 检查是否有block.obj
                    block_path = os.path.join(models_folder, "block.obj")
                    if os.path.exists(block_path):
                        col.label(text="✓ block.obj存在", icon='CHECKMARK')
                    else:
                        col.label(text="⚠ block.obj不存在", icon='ERROR')
                else:
                    col.label(text="⚠ models文件夹不存在", icon='ERROR')
            else:
                col.label(text="⚠ 警告: 路径不存在", icon='ERROR')
        
        if scene.texture_base_path:
            col.label(text=f"贴图路径: {scene.texture_base_path}", icon='INFO')
            
            # 检查路径是否存在
            if os.path.exists(scene.texture_base_path):
                col.label(text="✓ 路径存在", icon='CHECKMARK')
            else:
                col.label(text="⚠ 警告: 路径不存在", icon='ERROR')
        
        # 基础设置
        box = layout.box()
        box.label(text="基础设置", icon='SETTINGS')
        
        # 缩放模式设置
        col = box.column(align=True)
        col.label(text="缩放模式:")
        col.prop(settings, "scale_mode", text="")
        
        if settings.scale_mode == 'CUSTOM':
            col.prop(settings, "custom_scale_factor", text="自定义缩放")
        
        # 基础网格大小设置
        row = box.row()
        row.label(text="基础网格大小:")
        row.prop(settings, "base_block_size", text="")
        
        # 方向设置
        col = box.column(align=True)
        col.label(text="方块方向:")
        col.prop(settings, "direction_mode", text="")
        
        # 定位设置
        col = box.column(align=True)
        col.label(text="定位模式:")
        col.prop(settings, "positioning_mode", text="")
        
        # 相邻模式
        col.prop(settings, "adjacent_mode", text="启用相邻模式")
        
        # 自发光设置
        col = box.column(align=True)
        col.label(text="自发光强度:")
        col.prop(settings, "emission_strength", text="")
        
        # 测试和调试按钮
        col.operator("object.debug_position_calculation", text="调试位置计算", icon='CONSOLE')
        col.operator("object.test_mapping_system", text="测试映射系统", icon='MODIFIER')
        col.operator("object.test_submodel_emission_material", text="测试自发光材质", icon='LIGHT_SUN')
        
        # 位置信息
        box = layout.box()
        box.label(text="位置信息", icon='TEXT')
        
        col = box.column(align=True)
        
        row = col.row(align=True)
        row.operator("object.import_positions", text="导入位置", icon='IMPORT')
        
        if scene.grid_coordinates.strip():
            coordinates = parse_coordinate_string(scene.grid_coordinates)
            if coordinates:
                id_counts = {}
                for coord in coordinates:
                    position_id = coord['id']
                    id_counts[position_id] = id_counts.get(position_id, 0) + 1
                
                col.label(text=f"已解析 {len(coordinates)} 个坐标", icon='INFO')
                col.label(text=f"包含 {len(id_counts)} 种不同位置ID", icon='INFO')
                
                # 显示ID统计
                if len(id_counts) <= 10:
                    for pid, count in sorted(id_counts.items()):
                        col.label(text=f"  ID {pid}: {count} 个", icon='DOT')
        
        # 生成按钮
        col.operator("object.generate_from_grid", text="生成方块", icon='CUBE')
        
        # 管理工具
        box = layout.box()
        box.label(text="管理工具", icon='TOOL_SETTINGS')
        
        col = box.column(align=True)
        
        # 第一行：清理相关按钮
        row = col.row(align=True)
        row.operator("object.clear_all_blocks", text="清空所有方块", icon='TRASH')
        row.operator("object.clear_all_templates", text="清除模板", icon='TRASH')
        
        # 第二行：重新加载映射表和清理重复材质
        row = col.row(align=True)
        row.operator("object.reload_mapping_table", text="重新加载映射表", icon='FILE_REFRESH')
        row.operator("object.cleanup_duplicate_materials", text="清理重复材质", icon='MATERIAL')
        
        # 第三行：清除所有（包括映射表）
        row = col.row(align=True)
        row.operator("object.clear_all_templates_and_mapping", text="清除所有（包括映射表）", icon='CANCEL')
        
        # 说明
        box = layout.box()
        box.label(text="说明", icon='INFO')
        
        col = box.column(align=True)
        col.label(text="坐标格式: x,y,z,id (每行一个)")
        col.label(text="示例: -4,0,9,1")
        col.label(text="映射表格式: CSV文件，第7、45、46字段控制模型")
        col.label(text="第7字段: blocktype决定材质系统")
        col.label(text="第45字段: 主贴图前缀")
        col.label(text="第46字段: 子模型名称")
        col.label(text="主模型: models/block.obj (teamspawn类型使用id/teamspawn.obj)")
        col.label(text="子模型: {id}/{name}.obj")
        col.label(text="主贴图: {id}/hupo_[x|y|z].png")
        col.label(text="子贴图: {id}/{name}.png")
        col.label(text="子自发光: {id}/{name}_emi.png")
        col.label(text="材质系统: 根据blocktype自动选择")
        col.label(text="teamspawn: 只使用一个材质球，贴图处理模型和正常数组相反")
        col.label(text="minestone: 所有面使用同一个贴图，Z面和-Z面已修复UV映射")
        col.label(text="soil/plantash: Z面特殊，其他面相同")
        col.label(text="teamspawn: 强制使用主模型(id/teamspawn.obj)，使用teamspawn0贴图，全部面同一材质")
        col.label(text="replicator: 根据有无主贴图决定材质系统")
        col.label(text="相邻模式: 根据模型尺寸调整位置")
        col.label(text="定位模式: 模型中心或底部对齐")
        col.label(text="UV镜像: Z和-Z面镜像X轴并向左旋转90度")
        col.label(text="材质共享: 相同ID和面类型使用相同材质球")
        col.label(text="自发光支持: 子模型支持自发光贴图混合")
        col.label(text="修复: 材质名称重复和Z面贴图问题")
        col.label(text="修复: buildblueprint类型使用minestone系统")
        col.label(text="修复: 映射表重新加载问题")
        col.label(text="新增: teamspawn类型支持id/teamspawn.obj")
        col.label(text="修复: Z面和-Z面UV映射问题")
        col.label(text="新增: teamspawn类型独立材质系统，只使用一个材质球")
        col.label(text="修复: 尺寸缩放问题，现在在模板创建时正确应用缩放")
        col.label(text="新增: 重新加载映射表功能，清空模板时保留路径设置")
        col.label(text="注意: 保持OBJ导入的原始精度，不进行四舍五入")

# ============================================================================
# 注册函数
# ============================================================================

def register():
    """注册所有类"""
    classes = [
        BlockModelItem,
        BlockGeneratorSettings,
        OBJECT_OT_load_block_models,
        OBJECT_OT_set_texture_base_path,
        OBJECT_OT_set_models_base_path,
        OBJECT_OT_load_mapping_table,
        OBJECT_OT_reload_mapping_table,
        OBJECT_OT_import_positions,
        OBJECT_OT_generate_from_grid,
        OBJECT_OT_clear_all_blocks,
        OBJECT_OT_clear_all_templates,
        OBJECT_OT_clear_all_templates_and_mapping,
        OBJECT_OT_debug_position_calculation,
        OBJECT_OT_test_mapping_system,
        OBJECT_OT_test_submodel_emission_material,
        OBJECT_OT_cleanup_duplicate_materials,
        VIEW3D_PT_block_generator_main,
    ]
    
    for cls in classes:
        try:
            bpy.utils.register_class(cls)
        except Exception as e:
            print(f"注册类 {cls.__name__} 失败: {e}")
    
    # 场景属性
    bpy.types.Scene.block_generator_settings = bpy.props.PointerProperty(type=BlockGeneratorSettings)
    
    bpy.types.Scene.grid_coordinates = bpy.props.StringProperty(
        name="坐标信息",
        description="方块位置信息，格式: x,y,z,id (id在最后，对应位置ID)",
        default="",
    )
    
    bpy.types.Scene.texture_base_path = bpy.props.StringProperty(
        name="贴图基础路径",
        description="贴图文件的基础路径，例如: F:/Project/blender/pluge/black/",
        default="",
        subtype='DIR_PATH'
    )
    
    bpy.types.Scene.models_base_path = bpy.props.StringProperty(
        name="模型基础路径",
        description="模型文件的基础路径，例如: F:/Project/blender/pluge/",
        default="",
        subtype='DIR_PATH'
    )
    
    bpy.types.Scene.mapping_table_path = bpy.props.StringProperty(
        name="映射表路径",
        description="映射表文件路径",
        default="",
        subtype='FILE_PATH'
    )
    
    bpy.types.Scene.block_models = bpy.props.CollectionProperty(type=BlockModelItem)
    bpy.types.Scene.block_models_index = bpy.props.IntProperty(name="当前模型索引")

def unregister():
    """取消注册所有类"""
    classes = [
        VIEW3D_PT_block_generator_main,
        OBJECT_OT_cleanup_duplicate_materials,
        OBJECT_OT_test_submodel_emission_material,
        OBJECT_OT_test_mapping_system,
        OBJECT_OT_debug_position_calculation,
        OBJECT_OT_clear_all_templates_and_mapping,
        OBJECT_OT_clear_all_templates,
        OBJECT_OT_clear_all_blocks,
        OBJECT_OT_generate_from_grid,
        OBJECT_OT_import_positions,
        OBJECT_OT_reload_mapping_table,
        OBJECT_OT_load_mapping_table,
        OBJECT_OT_set_models_base_path,
        OBJECT_OT_set_texture_base_path,
        OBJECT_OT_load_block_models,
        BlockGeneratorSettings,
        BlockModelItem,
    ]
    
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
    
    # 删除自定义属性
    try:
        del bpy.types.Scene.block_generator_settings
        del bpy.types.Scene.grid_coordinates
        del bpy.types.Scene.texture_base_path
        del bpy.types.Scene.models_base_path
        del bpy.types.Scene.mapping_table_path
        del bpy.types.Scene.block_models
        del bpy.types.Scene.block_models_index
    except:
        pass

if __name__ == "__main__":
    register()