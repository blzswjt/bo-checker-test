"""
数据建模识别规范 - 所有元素类型的规则知识库

包含：主题域分类、主题域分组、主题域、业务对象、逻辑实体、业务属性

模块分区：
  1. 规则定义: ELEMENT_RULES（识别/命名/定义规则 + 正反例）
  2. Prompt构建: build_check_prompt, build_batch_prompt
  3. 工具函数: get_all_rules_text, get_rule_detail, recommend_element_type
"""
import json
import copy
from pathlib import Path

# 所有支持的元素类型
ELEMENT_TYPES = [
    "主题域分类", "主题域分组", "主题域",
    "业务对象", "逻辑实体", "业务属性"
]

# ============================================================
# 各元素类型的识别规则
# ============================================================

ELEMENT_RULES = {
    "主题域分类": {
        "description": "与BA的流程架构L1对齐的最高层级分类",
        "identification": [
            {"rule": "与BA对齐", "desc": "同BA的流程架构L1对齐", "positive": "管理采购", "negative": ""}
        ],
        "naming": [
            {"rule": "全局唯一", "desc": "全局唯一，无歧义", "positive": "管理采购", "negative": ""}
        ],
        "not_examples": [],
    },
    "主题域分组": {
        "description": "与BA的流程架构L2对齐的分组",
        "identification": [
            {"rule": "与BA对齐", "desc": "同BA的流程架构L2对齐", "positive": "管理采购履行", "negative": ""}
        ],
        "naming": [
            {"rule": "全局唯一", "desc": "全局唯一，无歧义", "positive": "管理采购履行", "negative": ""}
        ],
        "not_examples": [],
    },
    "主题域": {
        "description": "与BA的流程架构L3对齐的主题域",
        "identification": [
            {"rule": "与BA对齐", "desc": "同BA的流程架构L3对齐", "positive": "管理采购需求", "negative": ""}
        ],
        "naming": [
            {"rule": "全局唯一", "desc": "全局唯一，无歧义", "positive": "管理采购需求", "negative": ""}
        ],
        "not_examples": [],
    },
    "业务对象": {
        "description": "企业运作和管理过程中不可缺少的重要人、事、物、地信息。来源于业务流程的表、证、单、书，而非IT系统视角。通常会建立相应流程、组织和IT进行管理。",
        "identification": [
            {"rule": "企业运作中不可缺少的重要人、事、物、地信息", "desc": "基于商业设计、价值流或BI视角识别，而非IT系统视角。通常对应业务流程中的表、证、单、书等核心单据。应与业务能力匹配，有相应流程、组织和IT进行管理。若从IT数据表逆向识别，需排除纯技术对象（如接口表、日志表）。",
             "positive": "在采购管理领域，采购需求作为采购流程的源头单据，承接前端业务需求，驱动货源确认、订单下达、到货验收等环节", "negative": ""},
            {"rule": "有唯一的身份标识信息", "desc": "有唯一性身份标识信息，能区分业务对象的实例，且标识在生命周期内保持不变。其他属性可慢变或经常变化，但业务对象不发生本质变化。唯一性范围为全局唯一而非局部唯一。主键为单一业务编号则支持；主键为'父键+行号'的复联合主键或纯技术自增ID则不支持。",
             "positive": "每一次采购需求单内容都不相同，因此采购需求有采购需求编号唯一标识", "negative": "将采购需求行作为业务对象是错误的，因为采购需求行没有独立身份标识，行号在每个需求编号下重新编码（不是全局唯一）"},
            {"rule": "相对独立并有一组实体描述", "desc": "业务对象可独立存在、可获取、可传输、可使用并发挥价值。以主逻辑实体为核心，其他逻辑实体通过外键关系递归关联。与主逻辑实体同主键的1:1扩展表/垂直拆分表/历史归档表应合并进同一业务对象；纯多对多关联表归为关系实体。",
             "positive": "采购需求与供应商、采购订单等业务对象相对独立，由采购需求头、采购需求行等一组逻辑实体描述", "negative": "将采购需求行作为业务对象是错误的，因为采购需求行不能独立存在，其依赖于采购需求头"},
            {"rule": "有生命周期和状态变化", "desc": "业务对象有生命周期，有状态变化。不同生命周期状态划分类型（枚举值）不一样的人事物地，应识别为不同的业务对象。基础数据（码值、分类）和观测数据通常无状态变化，不属于业务对象。",
             "positive": "采购需求有生命周期状态：草稿、审核中、已审批、已驳回、已退回、已作废", "negative": "基础数据无状态变更（变更基本是新加码值）；观测数据不会被修改"},
            {"rule": "责任主体可确权", "desc": "业务对象有明确的归属领域，在该业务领域进行全生命周期管理。必须有明确的业务部门作为数据Owner，履行标准制定、质量管控、安全管理等职责。若本领域只是引用/消费该业务对象（仅存外键或冗余快照字段），则不在本领域识别。",
             "positive": "采购订单归属于采购管理领域，采购部门是采购订单全生命周期的管理者，是数据的Owner", "negative": "人力资源管理部门将'身份证'识别为业务对象是错误的，因为不负责身份证的制证、发证、换证、注销等全生命周期管理"},
            {"rule": "可实例化", "desc": "业务对象的实例可以发生业务行为，实例集合不可提前预知、不限定数量。通常需明确Owner、定义架构、标准、度量监控才能有效管理。基础数据（分类/标签）码值有限且可预置，无业务行为；报告报表数据无法实例化。",
             "positive": "采购需求有很多次需求，次数无法预置、不限；有创建、审批、退回、取消等业务行为", "negative": "基础数据是分类/标签，无业务行为（如采购需求类型）；报告报表数据无法实例化"},
        ],
        "naming": [
            {"rule": "名称唯一", "desc": "名称在整个数据模型中具有唯一性。同名必统一：相同名称的业务对象必须是同一事物。不同业务对象必须使用不同名称。跨领域也需全局唯一。", "positive": "业务对象'采购需求'，名称企业内唯一", "negative": "直接采购需求、间接采购需求、服务采购需求如果逻辑实体属性不同，需拆分为三个业务对象且名称不能相同"},
            {"rule": "名词命名", "desc": "名称原则上必须是名词，表达'是什么'而非'做什么'。不使用介词/连词等虚词（在、被、的等均应去除），中文名称尽量避免英文，禁止使用符号，开始和末尾原则上禁止使用数字。", "positive": "采购需求", "negative": "采购需求申请"},
            {"rule": "符合行规", "desc": "名称能够完整准确表述业务含义，符合企业内、行业内的通用习惯和规范。优先使用行业标准术语，避免自造词、口语化表达。", "positive": "采购需求", "negative": "采需单"},
        ],
        "not_examples": [
            "基础数据/码值/分类/标签（如：采购需求类型、币种、国家代码）",
            "业务对象的子实体/行项目（如：采购需求行、订单明细行）",
            "观测数据/报告/报表数据",
            "属性/字段（如：金额、日期、数量）",
            "操作/动作/行为（如：审批、提交）",
            "系统/模块/功能（如：采购系统、报表模块）",
        ],
        "definition": [
            {"rule": "编码唯一", "desc": "业务对象元素的编码在企业内唯一，并遵循相同的编码规范。编码应包含可识别的分类信息（如领域前缀），有统一长度和格式。", "positive": "BOPUR001（BO+领域缩写+3位序列号）", "negative": "不同领域编码规范不一致，有'BO'开头，有的是序列号，有的'YWDX'开头"},
            {"rule": "描述内容完整", "desc": "业务对象应有明确的描述，包括目的（为什么对业务重要）、定义（是什么）和范围（含哪些），范围不应局限于某类产品。应具有业务语义而非技术描述，慎用'记录XXX'这种技术语言。", "positive": "采购需求是企业对物资/服务的采购申请与业务承诺，是采购交易处理过程中的单据记录，驱动采购计划与订单下达，支撑成本归集与费用管控。包括直接采购需求、间接采购需求、服务采购需求。", "negative": "采购需求为了实现采购需求单管理，记录采购的内容和事项（太宽泛、等于什么都没说）"},
        ],
    },
    "逻辑实体": {
        "description": "描述业务对象不同业务特征的一组密切相关的属性集合，有独立完整业务语义。逻辑数据实体依赖于业务对象。",
        "identification": [
            {"rule": "一组属性集合", "desc": "描述业务对象某方面业务特征的一组密切相关属性的集合，有独立完整业务语义。属性围绕同一个业务概念，不可随意拆分，不会出现'部分属性有值、另一部分永远为空'，业务上作为一个整体被认知和使用。",
             "positive": "采购订单头中包含采购订单编号、供应商编码、订单日期、采购组织、货币类型、总金额、付款条款、订单状态，属性紧密依附订单头，语义统一", "negative": "强行把采购订单头+供应商银行信息合并为一个逻辑实体"},
            {"rule": "遵循三范式", "desc": "逻辑实体设计必须遵循第三范式。每个实体的属性不应重复定义，不应包含其他逻辑实体中的非关键字属性。通过外键关联而非冗余存储获取其他实体的属性。",
             "positive": "采购订单头中只包含供应商编码，不冗余包含供应商名称", "negative": "采购订单头中包含供应商编码，又冗余包含供应商名称"},
            {"rule": "剔除技术数据和衍生数据", "desc": "剔除技术数据（作业配置表、元数据表、技术参数配置表、接口表、映射转换表等）、衍生数据（历史表、中间表、临时表、备份表、统计报表等）、日志数据（用户操作日志、系统日志、校验日志等）。逻辑实体应具有独立的业务语义。",
             "positive": "", "negative": "采购需求发布任务表、采购结算单接口表、采购订单接口头表等技术数据；采购需求行宽表属于衍生数据"},
        ],
        "naming": [
            {"rule": "名称唯一", "desc": "实体命名在整个数据模型中具有唯一性，同名必统一。不同业务对象下的逻辑实体也不得重名。", "positive": "逻辑实体'采购需求头'，企业内只有一个", "negative": "存在多个重复的逻辑实体'采购需求头'"},
            {"rule": "名词命名", "desc": "逻辑实体名称原则上必须是名词，不使用动词或动宾短语命名，表达'是什么'而非'做什么'。", "positive": "采购需求头", "negative": "采购申请（动宾结构）"},
            {"rule": "避免虚词", "desc": "不使用介词/连词等虚词（在、被、的等均应去除），中文名称尽量避免英文，禁止使用符号，开始和末尾原则上禁止使用数字。", "positive": "采购需求头", "negative": "采购需求头1"},
            {"rule": "符合行规", "desc": "名称能够完整准确表述业务含义，符合企业内、行业内的通用习惯和规范。用字规范，注意行业特定用字要求。", "positive": "供应商账户", "negative": "供应商帐户（财政部要求财经相关用'账'不用'帐'）"},
            {"rule": "关系实体命名规范", "desc": "命名格式为'实体1和实体2关系'。关联的实体1和实体2必须存在。根据关系实体归属原则，后产生的实体在名称中放在后方。不得省略关联实体名称。", "positive": "采购需求和采购订单分摊关系", "negative": "采购订单分摊关系（缺少实体1）"},
            {"rule": "剔除特定关键字", "desc": "实体命名中不能带'表、文件、菜单和报告'等关键字。特定业务场景除外（如财务领域的'资产负债表'、'利润表'）。", "positive": "采购需求头", "negative": "采购需求头表"},
        ],
        "not_examples": [
            "技术数据表（如：接口表、发布任务表、配置表）",
            "衍生数据（如：宽表、汇总表、临时表、备份表）",
            "日志数据（如：操作日志、系统日志）",
            "独立的业务对象（逻辑实体必须依附于业务对象）",
        ],
        "definition": [
            {"rule": "关系实体归属原则", "desc": "关系实体必须归属于唯一的业务对象。先后顺序原则：建立关系的实体在业务上如有产生先后顺序，归属到后产生的实体所属业务对象。业务主责原则：判断业务的主责管理方，放置在主责管理的一方。两原则冲突时以业务主责优先。", "positive": "采购需求关系、采购需求行关系归属于业务对象'采购需求'", "negative": "逻辑实体'采购订单关系'不能归属于'采购需求'，应归属于'采购订单'"},
            {"rule": "编码唯一", "desc": "逻辑实体元素的编码在企业内唯一，并遵循相同的编码规范。编码应包含可识别的分类信息。", "positive": "LEPUR0001（LE+领域缩写+4位序列号）", "negative": "不同领域编码规范不一致"},
            {"rule": "主逻辑实体唯一", "desc": "每个业务对象有且只有一个主逻辑实体，表述业务对象的主要业务关注。其他实体都是围绕主逻辑实体建立关联关系。主逻辑实体建立后其他实体才能被建立；其他实体消亡后主逻辑实体最后才可消亡。", "positive": "业务对象'采购需求'中包含一个'采购需求头'主逻辑实体", "negative": "包含'采购需求头'和'采购需求行'两个主逻辑实体"},
            {"rule": "必须有主键", "desc": "实体应具有业务主键，用于唯一标识一个逻辑实体内的数据。主键值不能为空且必须唯一，应具有业务含义而非纯技术流水号。", "positive": "采购需求头的主键是'采购需求编号'", "negative": "没有设置主键"},
            {"rule": "主键稳定", "desc": "标识符的取值在其生命周期过程中不应变化或废止，适用于该实体的所有取值样本。避免使用会发生变更的业务属性作为主键。", "positive": "采购需求编号一经产生，就不会被修改", "negative": "用采购需求名称做主键"},
            {"rule": "主键有业务含义", "desc": "主键有业务含义，对所有用户而言均可获取、理解和使用。主键中可编码业务信息（如组织、日期、类型等）。避免使用纯系统生成的无意义流水号。", "positive": "采购需求编号280020260604000004，标识管理单元2800下在2026年6月4日创建的第4单需求", "negative": "采购需求ID为1968161303673506831，只是系统生成的唯一流水号，不具备可识别性"},
            {"rule": "实体归属唯一", "desc": "逻辑实体必须归属于唯一的业务对象，不得同时归属于多个业务对象。归属应基于业务主责原则确定，其他业务对象通过关联关系引用。", "positive": "采购需求关系、采购需求行关系归属于业务对象'采购需求'", "negative": "'采购订单关系'即归属于'采购需求'又归属于'采购订单'，应只归属于'采购订单'"},
            {"rule": "描述内容完整", "desc": "逻辑实体应有明确的描述，包括目的（为什么对业务重要）和定义（是什么，描述什么业务信息）。应具有业务语义而非技术描述，慎用'记录XXX'这种技术语言。", "positive": "采购需求头：是指一份采购需求申请单的摘要和控制信息，用于汇总一份完整的物资或服务申请，并驱动后续的审批、寻源和采购流程。主要属性包括：需求单号、申请人、申请部门、需求日期、需求状态、采购类型等。", "negative": "采购需求头：是记录采购需求部门提交的申请信息（太肤浅、太偏物理表设计）"},
        ],
    },
    "业务属性": {
        "description": "逻辑实体下的最小业务语义单元，不可再拆分。每个属性只表达一个业务含义。",
        "identification": [
            {"rule": "原子性", "desc": "业务属性必须是最小业务语义单元，不可再拆分为多个有独立意义的子属性。每个属性只表达一个业务含义。一条记录内不能出现多值。如果一个概念还能拆出多个属性，它可能是实体而非属性。",
             "positive": "采购需求行号", "negative": "采购需求行（这是逻辑实体不是属性）；客户联系电话如有多个需拆分设计为逻辑实体"},
            {"rule": "必要性", "desc": "识别的每一个业务属性都有明确的含义和用途，满足业务需求。不为不存在的业务场景预留属性。可通过计算或推导获得的属性一般不冗余存储。",
             "positive": "采购需求行中包含'需求日期'", "negative": "采购需求行中包含'发货日期'（不属于采购需求）；采购订单中未包含'采购金额'，因为采购金额有抹零、一口价等场景无法简单计算获得"},
            {"rule": "剔除技术字段", "desc": "无业务含义的技术字段不作为属性纳入业务逻辑模型（在物理模型阶段再考虑）。需剔除的典型技术字段包括：租户ID、删除标记、创建人、最后修改人、最后修改日期、最后修改跟踪ID、最后修改版本等。字段名称末尾以'ID'结尾的，一律修改'ID'为'编码'。",
             "positive": "剔除租户ID、删除标记、创建人、最后修改人、最后修改日期等", "negative": "没有剔除租户ID、删除标记、创建人、最后修改人等"},
        ],
        "naming": [
            {"rule": "业务词汇", "desc": "采用正式业务词汇，而非口语化表达。命名应具有通用性，不局限于特定场景的俗称。与企业业务术语库保持一致。", "positive": "物料编码", "negative": "原料编码（太口语化且场景狭窄，不是正式业务词汇）"},
            {"rule": "名称贯标", "desc": "属性命名企业级唯一且共享，遵循数据标准。不能有同义不同名、或同名不同义情况。命名规范尽量和数据标准的数据项定义保持一致。", "positive": "采购需求编号（属于数据标准定义的内容）", "negative": "采购需求号码（不是数据标准定义的内容）"},
            {"rule": "顾名思义", "desc": "属性名称应清晰、见名知义、易于理解。直接表达属性的业务含义，避免使用缩写、简称导致的理解困难。", "positive": "采购单价", "negative": "请购单价"},
            {"rule": "词汇简练", "desc": "用尽可能简练的词汇唯一标识属性并表达含义。去除不必要的修饰词和重复信息，避免将实体名称重复嵌入属性名称。在不产生歧义的前提下尽量简短。", "positive": "自动创建标识", "negative": "采购需求自动创建标识（实体名已明确，无需重复）"},
            {"rule": "少用特殊字符", "desc": "尽可能少使用程序和SQL中的关键词、算式运算相关的符号等特殊字符，避免引起冲突。避免使用&、-、+、/、*等符号和数据库保留关键字。", "positive": "", "negative": "名称包含'&'、'-'、'+'、'/'、'*'等"},
        ],
        "not_examples": [
            "技术字段（租户ID、删除标记、创建人、最后修改人等）",
            "逻辑实体（如采购需求行是实体不是属性）",
            "可拆分的复合字段",
            "无明确用途的摆设属性",
        ],
        "definition": [],
    },
}

# 默认规则备份（用于重置）
_DEFAULT_RULES = copy.deepcopy(ELEMENT_RULES)

# 规则配置文件路径
_RULES_CONFIG_PATH = Path(__file__).parent / "rules_config.json"

# ============================================================
# 规则版本管理
# ============================================================
# 内存中的版本存储: {version_name: {rules: {...}, created: "..."}}
_rule_versions: dict = {}
_active_version: str = "默认"


def _serialize_rules() -> dict:
    """序列化当前 ELEMENT_RULES 为可存储的 dict"""
    data = {}
    for etype, rules in ELEMENT_RULES.items():
        data[etype] = {
            "description": rules.get("description", ""),
            "identification": rules.get("identification", []),
            "naming": rules.get("naming", []),
            "definition": rules.get("definition", []),
            "not_examples": rules.get("not_examples", []),
            "disabled": rules.get("disabled", False),
        }
    return data


def _apply_rules(rules_data: dict):
    """将 rules_data 应用到 ELEMENT_RULES"""
    global ELEMENT_RULES
    ELEMENT_RULES = copy.deepcopy(_DEFAULT_RULES)
    for etype, rules in rules_data.items():
        if etype in ELEMENT_RULES:
            for key in ["identification", "naming", "definition"]:
                if key in rules:
                    ELEMENT_RULES[etype][key] = rules[key]
            if "description" in rules:
                ELEMENT_RULES[etype]["description"] = rules["description"]
            if "not_examples" in rules:
                ELEMENT_RULES[etype]["not_examples"] = rules["not_examples"]
            if "disabled" in rules:
                ELEMENT_RULES[etype]["disabled"] = rules["disabled"]


def _save_versions_to_file():
    """将版本数据持久化到 rules_config.json"""
    data = {
        "versions": _rule_versions,
        "active_version": _active_version,
    }
    with open(_RULES_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_rules_config():
    """从 rules_config.json 加载版本数据，激活当前版本"""
    global _rule_versions, _active_version
    if not _RULES_CONFIG_PATH.exists():
        # 初始化默认版本
        _rule_versions["默认"] = {"rules": _serialize_rules(), "created": ""}
        return
    try:
        with open(_RULES_CONFIG_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # 新版本格式
        if "versions" in data:
            _rule_versions = data["versions"]
            _active_version = data.get("active_version", "默认")
            if _active_version in _rule_versions:
                _apply_rules(_rule_versions[_active_version]["rules"])
        else:
            # 旧版本格式（向后兼容）：直接是 rules 数据
            _rule_versions["默认"] = {"rules": data, "created": ""}
            _apply_rules(data)
    except Exception:
        _rule_versions["默认"] = {"rules": _serialize_rules(), "created": ""}


def save_rules_config():
    """将当前 ELEMENT_RULES 保存到当前激活版本"""
    if _active_version in _rule_versions:
        _rule_versions[_active_version]["rules"] = _serialize_rules()
    else:
        _rule_versions[_active_version] = {"rules": _serialize_rules(), "created": ""}
    _save_versions_to_file()


def reset_rules_config():
    """重置当前版本规则为默认值"""
    global ELEMENT_RULES
    ELEMENT_RULES = copy.deepcopy(_DEFAULT_RULES)
    if _active_version in _rule_versions:
        _rule_versions[_active_version]["rules"] = _serialize_rules()
        _save_versions_to_file()


def get_rules_config() -> dict:
    """返回当前激活版本的完整规则配置"""
    return _serialize_rules()


def update_rules_config(new_config: dict):
    """用前端传来的配置更新当前版本规则"""
    global ELEMENT_RULES
    for etype, rules in new_config.items():
        if etype in ELEMENT_RULES:
            for key in ["description", "identification", "naming", "definition", "not_examples", "disabled"]:
                if key in rules:
                    ELEMENT_RULES[etype][key] = rules[key]
    save_rules_config()


# ---- 版本管理 API ----

def list_rule_versions() -> list:
    """返回所有版本名称列表"""
    return [{"name": name, "active": name == _active_version,
             "created": v.get("created", "")}
            for name, v in _rule_versions.items()]


def create_rule_version(name: str, copy_from: str = None) -> bool:
    """创建新版本，可从已有版本复制"""
    global _active_version
    if not name or name in _rule_versions:
        return False
    if copy_from and copy_from in _rule_versions:
        rules = copy.deepcopy(_rule_versions[copy_from]["rules"])
    else:
        rules = _serialize_rules()
    from datetime import datetime
    _rule_versions[name] = {"rules": rules, "created": datetime.now().strftime("%Y-%m-%d %H:%M")}
    _save_versions_to_file()
    return True


def delete_rule_version(name: str) -> bool:
    """删除版本（不允许删除默认）"""
    global _active_version
    if name == "默认" or name not in _rule_versions:
        return False
    del _rule_versions[name]
    if _active_version == name:
        _active_version = "默认"
        if "默认" in _rule_versions:
            _apply_rules(_rule_versions["默认"]["rules"])
    _save_versions_to_file()
    return True


def rename_rule_version(old_name: str, new_name: str) -> bool:
    """重命名版本"""
    global _active_version
    if old_name not in _rule_versions or new_name in _rule_versions or not new_name:
        return False
    _rule_versions[new_name] = _rule_versions.pop(old_name)
    if _active_version == old_name:
        _active_version = new_name
    _save_versions_to_file()
    return True


def switch_rule_version(name: str) -> bool:
    """切换到指定版本，更新 ELEMENT_RULES"""
    global _active_version
    if name not in _rule_versions:
        return False
    _active_version = name
    _apply_rules(_rule_versions[name]["rules"])
    _save_versions_to_file()
    return True


def get_version_rules(name: str) -> dict:
    """获取指定版本的规则配置"""
    if name in _rule_versions:
        return _rule_versions[name]["rules"]
    return {}


# 启动时加载自定义配置
load_rules_config()


# ============================================================
# 2. Prompt 构建
# ============================================================

def build_check_prompt(element_type: str) -> str:
    """根据元素类型构建识别 Prompt"""
    rules = ELEMENT_RULES.get(element_type)
    if not rules:
        return ""

    parts = [f"你是一个数据治理专家，专门负责判断某个事物是否符合「{element_type}」的定义。"]
    parts.append(f"\n## {element_type}的定义\n{rules['description']}")

    # 识别规则
    parts.append(f"\n## 识别规则（需全部满足）")
    for i, r in enumerate(rules["identification"], 1):
        parts.append(f"\n{i}. **{r['rule']}**：{r['desc']}")
        if r.get("positive"):
            parts.append(f"   - 正例：{r['positive']}")
        if r.get("negative"):
            parts.append(f"   - 反例：{r['negative']}")

    # 命名规则
    parts.append(f"\n## 命名规则")
    for i, r in enumerate(rules["naming"], 1):
        parts.append(f"\n{i}. **{r['rule']}**：{r['desc']}")
        if r.get("positive"):
            parts.append(f"   - 正例：{r['positive']}")
        if r.get("negative"):
            parts.append(f"   - 反例：{r['negative']}")

    # 常见反例
    if rules.get("not_examples"):
        parts.append(f"\n## 常见不是{element_type}的情况")
        for ex in rules["not_examples"]:
            parts.append(f"- {ex}")

    parts.append(f"""
## 判断要求
请对给定的事物逐条规则分析，最后给出明确结论。

输出格式：
- **结论：** ✅ 是{element_type} / ❌ 不是{element_type} / ⚠️ 无法确定
- **理由：** 逐条规则分析""")

    return "\n".join(parts)


def build_batch_prompt(element_type: str, items_text: str, kb_examples: dict = None, context_map: dict = None,
                       include_naming: bool = True, include_definition: bool = True,
                       analysis_context: str = None) -> str:
    """构建批量识别 Prompt，集成知识库示例、业务上下文和逐条规则分析
    
    include_naming: 是否包含命名规则（默认包含）
    include_definition: 是否包含定义规则（默认包含）
    """
    rules = ELEMENT_RULES.get(element_type)
    if not rules:
        return ""

    # 规则详情 - 识别规则始终包含（过滤掉 enabled=false 的规则）
    id_rules = [r for r in rules["identification"] if r.get("enabled", True) is not False]
    nm_rules = [r for r in rules.get("naming", []) if r.get("enabled", True) is not False] if include_naming else []
    df_rules = [r for r in rules.get("definition", []) if r.get("enabled", True) is not False] if include_definition else []
    
    id_detail = ""
    for i, r in enumerate(id_rules, 1):
        id_detail += f"\n{i}. 【{r['rule']}】{r['desc']}"
        if r.get("positive"):
            id_detail += f"（正例：{r['positive']}）"
        if r.get("negative"):
            id_detail += f"（反例：{r['negative']}）"

    nm_detail = ""
    if nm_rules:
        for i, r in enumerate(nm_rules, 1):
            nm_detail += f"\n{i}. 【{r['rule']}】{r['desc']}"
            if r.get("positive"):
                nm_detail += f"（正例：{r['positive']}）"
            if r.get("negative"):
                nm_detail += f"（反例：{r['negative']}）"

    df_detail = ""
    if df_rules:
        for i, r in enumerate(df_rules, 1):
            df_detail += f"\n{i}. 【{r['rule']}】{r['desc']}"
            if r.get("positive"):
                df_detail += f"（正例：{r['positive']}）"
            if r.get("negative"):
                df_detail += f"（反例：{r['negative']}）"

    not_summary = ""
    if rules.get("not_examples"):
        not_summary = "\n常见不是的情况：" + "；".join(rules["not_examples"][:4])

    # 知识库已知示例
    kb_section = ""
    if kb_examples:
        pos = kb_examples.get("positive", [])
        neg = kb_examples.get("negative", [])
        if pos or neg:
            kb_section = "\n\n## 已知参考（用户已确认，请优先参考）"
            if pos:
                kb_section += "\n已确认是的：" + "、".join(f"{e['item']}（{e.get('reason','')}）" for e in pos[:6])
            if neg:
                kb_section += "\n已确认不是的：" + "、".join(f"{e['item']}（{e.get('reason','')}）" for e in neg[:6])

    # 构建所有规则名称列表供逐条分析（只包含启用的规则）
    all_rule_names = [r["rule"] for r in id_rules] + [r["rule"] for r in nm_rules] + [r["rule"] for r in df_rules]
    rule_names_json = json.dumps(all_rule_names, ensure_ascii=False)

    # 业务上下文信息
    context_section = ""
    if context_map:
        context_lines = []
        for item_name, ctx in context_map.items():
            # 优先用预拼接的 path，否则从 l1/l2/l3 拼接
            path = ctx.get('path', '')
            if not path:
                parts = []
                if ctx.get('l1'):
                    parts.append(ctx['l1'])
                if ctx.get('l2'):
                    parts.append(ctx['l2'])
                if ctx.get('l3'):
                    parts.append(ctx['l3'])
                path = ' → '.join(parts) if parts else ''
            line = f"- {item_name}"
            if path:
                line += f"（所属路径：{path}）"
            if ctx.get('definition'):
                line += f"\n  定义：{ctx['definition'][:100]}"
            context_lines.append(line)
        if context_lines:
            context_section = "\n\n## 业务上下文（来自Excel文件，请参考）\n" + "\n".join(context_lines)

    # AI 预分析上下文
    analysis_section = ""
    if analysis_context:
        # 截取前2000字符，避免 prompt 过长
        trimmed = analysis_context[:2000]
        if len(analysis_context) > 2000:
            trimmed += "\n...(分析内容已截断)"
        analysis_section = f"\n\n## 数据表预分析结果（来自 AI 分析，请参考）\n{trimmed}"

    # 条件性构建命名规则/定义规则区块
    naming_section = f"\n## 命名规则{nm_detail}" if nm_detail else ""
    definition_section = f"\n## 定义规则{df_detail}" if df_detail else ""
    
    # 规则分析范围描述
    rule_scope = "识别规则"
    if nm_detail and df_detail:
        rule_scope = "识别规则、命名规则、定义规则"
    elif nm_detail:
        rule_scope = "识别规则、命名规则"
    elif df_detail:
        rule_scope = "识别规则、定义规则"

    return f"""你是一个数据治理专家。请判断以下事物是否是「{element_type}」。

## {element_type}定义
{rules['description']}

## 识别规则（需全部满足）{id_detail}{naming_section}{definition_section}{not_summary}{kb_section}{context_section}{analysis_section}

## 输出要求

**第一步：先用自然语言对每个事物进行分析思考**

对每个事物逐条{rule_scope}分析，格式如：
**1. 事物名**
- 分析：简要分析这个事物是什么，与{element_type}的关系
- 规则判断：
  - ✓/✗ 【规则名】满足或不满足的原因
- 结论：是/不是/待人工

**第二步：最后输出JSON结果**

分析完所有事物后，输出最终JSON：
```json
{{"results": [{{
  "item": "事物名",
  "is_bo": true/false/null,
  "confidence": "high/medium/low",
  "reason": "总体简要理由",
  "rules_check": [{{"rule": "规则名", "pass": true/false, "reason": "满足或不满足的简要原因"}}]
}}]}}
```

说明：
- is_bo: true=是{element_type}, false=不是, null=无法确定需人工判断
- rules_check: 对所有规则逐一判断，rule名必须与上面的规则名完全一致

规则名列表：{rule_names_json}

待判断的事物列表：
{items_text}"""

# ============================================================
# 3. 工具函数
# ============================================================

def get_all_rules_text() -> dict:
    """返回所有元素类型的规则文本，供前端展示"""
    result = {}
    for etype, rules in ELEMENT_RULES.items():
        parts = [f"# {etype}\n{rules['description']}\n"]
        parts.append("## 识别规则")
        for r in rules["identification"]:
            status = "" if r.get("enabled", True) is not False else " ⛔禁用"
            parts.append(f"- **{r['rule']}**{status}：{r['desc']}")
        parts.append("\n## 命名规则")
        for r in rules["naming"]:
            status = "" if r.get("enabled", True) is not False else " ⛔禁用"
            parts.append(f"- **{r['rule']}**{status}：{r['desc']}")
        if rules.get("definition"):
            parts.append("\n## 定义规则")
            for r in rules["definition"]:
                status = "" if r.get("enabled", True) is not False else " ⛔禁用"
                parts.append(f"- **{r['rule']}**{status}：{r['desc']}")
        if rules.get("not_examples"):
            parts.append("\n## 常见反例")
            for ex in rules["not_examples"]:
                parts.append(f"- {ex}")
        result[etype] = "\n".join(parts)
    return result


def get_rule_detail(etype: str, rule_name: str) -> str:
    """获取某条规则的详细描述，用于答疑智能体"""
    rules = ELEMENT_RULES.get(etype, {})
    for category in ["identification", "naming", "definition"]:
        for r in rules.get(category, []):
            if r["rule"] == rule_name or rule_name in r["rule"] or r["rule"] in rule_name:
                cat_name = {"identification": "识别规则", "naming": "命名规则", "definition": "定义规则"}.get(category, category)
                return f"规则类别：{cat_name}\n规则名称：{r['rule']}\n规则描述：{r['desc']}"
    return f"规则名称：{rule_name}\n（未找到详细描述）"


# ============================================================
# 列名关键词 → 元素类型推荐映射
# ============================================================

COLUMN_TYPE_KEYWORDS = {
    "主题域分类": ["主题域分类", "分类名称", "L1"],
    "主题域分组": ["主题域分组", "分组名称", "L2"],
    "主题域": ["主题域名称", "主题域", "L3"],
    "业务对象": ["业务对象唯一标识", "业务对象名称", "业务对象编码", "业务对象"],
    "逻辑实体": ["逻辑实体名称", "逻辑实体唯一标识", "逻辑实体编码", "逻辑实体"],
    "业务属性": ["属性名称", "属性唯一标识", "属性编码", "业务属性", "业务属性名称"],
}


def recommend_element_type(column_name: str) -> str | None:
    """根据列名推荐最可能的元素类型"""
    col = column_name.strip()
    for etype, keywords in COLUMN_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in col:
                return etype
    return None
