import logging
import sqlite3
from sqlalchemy.orm import aliased
from sqlalchemy import create_engine
from sqlalchemy import Column, Integer, ForeignKey
from sqlalchemy import Column, Integer, String
from sqlalchemy import Column, Integer, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from sqlalchemy import Column, Integer, String, DateTime
from datetime import datetime, timedelta
import pytz
import os
import re
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine, Column, Integer, String, Text, JSON, Enum, DateTime, Date, ForeignKey, MetaData, func
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# 设置北京时间时区
beijing_tz = timezone(timedelta(hours=8))

# 在文件开头的导入部分之后添加
logger = logging.getLogger("pdfsummary")
if not logger.handlers:
    # 创建一个标准输出StreamHandler
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s'))
    logger.addHandler(stream_handler)
    logger.setLevel(logging.INFO)

# 数据库配置
_SQLITE_FALLBACK = (
    "sqlite:///"
    + os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "message_monitor.db")
)
DATABASE_URL = os.getenv(
    'DATABASE_URL',
    _SQLITE_FALLBACK,
)
SQLITE_DB_PATH = os.getenv(
    'WECHAT_SQLITE_DB_PATH',
    '/home/yy/project/Gewechat/vxbot/data/message_monitor.db',
)

# 初始化 SQLAlchemy
engine = create_engine(DATABASE_URL)
Session = sessionmaker(bind=engine)
session = Session()
Base = declarative_base()

# 表模型定义


class WxArticle(Base):
    __tablename__ = 'wx_article'

    id = Column(Integer, primary_key=True)         # 主键
    title = Column(String(255))                   # 标题
    content = Column(Text)                        # 内容
    author = Column(String(255))                  # 作者
    content_url = Column(String(1023))            # 详情链接
    create_time = Column(DateTime)                # 创建时间
    copyright_stat = Column(Integer)              # 版权状态
    comm = Column(Text)                           # 精选评论
    comm_reply = Column(Text)                     # 评论回复


class ProcessedArticle(Base):
    __tablename__ = 'processed_articles'

    id = Column(Integer, primary_key=True)
    original_id = Column(Integer)  # 移除外键关联，保留字段
    title = Column(String(1023))
    content = Column(Text)
    processed_summary = Column(Text)
    processed_key_info = Column(JSON)
    file_path = Column(String(1023))
    processed_time = Column(DateTime, default=lambda: datetime.now(beijing_tz))
    article_type = Column(Enum('general', 'recruitment',
                          'news', 'others'), default='general')
    content_url = Column(String(1023))
    account = Column(String(1023))
    publish_date = Column(Date, nullable=True)


class User(Base):
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True)
    name = Column(String(255))
    email = Column(String(255))


class UserTagSubscription(Base):
    __tablename__ = 'usertagsubscriptions'

    user_id = Column(Integer, ForeignKey('users.id'), primary_key=True)
    tag_id = Column(Integer, primary_key=True)


class AccountTag(Base):
    __tablename__ = 'account_tags'

    account_id = Column(Integer, ForeignKey('account.id'), primary_key=True)
    tag_id = Column(Integer, primary_key=True)


class Account(Base):
    __tablename__ = 'account'

    id = Column(Integer, primary_key=True)
    account_name = Column(String(255))


class UserSubscription(Base):
    __tablename__ = 'usersubscriptions'

    id = Column(Integer, primary_key=True, autoincrement=True)  # 主键，自增
    user_id = Column(Integer, ForeignKey('users.id'),
                     nullable=False)  # 用户ID，外键关联users表
    account_id = Column(Integer, ForeignKey('account.id'),
                        nullable=False)  # 公众号ID，外键关联account表


# 插入数据的封装函数


def insert_processed_article(original_id, title, content, processed_summary, processed_key_info, file_path, article_type, content_url, account, publish_date):
    """
    插入处理后的文章记录到 processed_articles 表。

    :param original_id: wx_article 表的 ID
    :param title: 文章标题
    :param content: 文章全文
    :param processed_summary: 文章摘要
    :param processed_key_info: 提取的关键信息（JSON 格式）
    :param file_path: 文件路径
    :param article_type: 文章类型（'general', 'recruitment', 'news', 'others'）
    :return: 插入的记录 ID 或 None
    """
    try:
        # 兼容 SQLite：Date 列只接受 date 对象（字符串来自 wechat_articles.created_at）
        if isinstance(publish_date, str):
            try:
                publish_date = datetime.strptime(
                    publish_date[:10], '%Y-%m-%d').date()
            except ValueError:
                publish_date = None
        # 创建记录
        new_article = ProcessedArticle(
            original_id=original_id,
            title=title,
            content=content,
            processed_summary=processed_summary,
            processed_key_info=processed_key_info,
            file_path=file_path,
            article_type=article_type,
            content_url=content_url,
            account=account,
            publish_date=publish_date
        )
        # 插入记录并提交
        session.add(new_article)
        session.commit()
        logger.info(f"成功插入记录: ID = {new_article.id}")
        return new_article.id
    except Exception as e:
        session.rollback()  # 回滚事务
        logger.info(f"插入记录失败: {e}")
        return None


def update_processed_article(article_id, content, column_name):
    """
    更新处理后的文章记录的指定字段。

    :param article_id: 文章 ID
    :param content: 更新的内容
    :param column_name: 更新的字段名
    :return: 更新的记录数
    """
    try:
        # 查询记录
        article = session.query(ProcessedArticle).filter_by(
            id=article_id).first()
        if article:
            # 更新字段
            setattr(article, column_name, content)
            session.commit()  # 提交事务
            logger.info(f"成功更新记录: ID = {article_id}")
            return 1
        else:
            logger.info(f"更新失败: 找不到 ID = {article_id} 的记录")
            return 0
    except Exception as e:
        session.rollback()  # 回滚事务
        logger.info(f"更新记录失败: {e}")
        return 0


def get_today_and_yesterday_file_paths(base_path):
    """
    查询 wx_article 表中今天创建的记录，仅生成今天和昨天的文件路径，检查文件是否存在并返回有效路径的字典。

    :param base_path: 基础路径，用于拼接生成文件路径
    :return: 一个字典 {id: file_path}，仅包含文件存在的路径
    """
    try:
        # 获取今天的日期范围
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=999999)

        # 获取今天和昨天的日期字符串
        today_date = today_start.strftime("%Y-%m-%d")
        yesterday_date = (today_start - timedelta(days=1)).strftime("%Y-%m-%d")

        # 查询今天的记录
        # records = session.query(WxArticle.id, WxArticle.title).filter(
        #     WxArticle.create_time >= today_start,
        #     WxArticle.create_time <= today_end
        # ).all()

        # 查询昨天的记录
        yesterday_records = session.query(WxArticle.id, WxArticle.title, WxArticle.create_time).filter(
            WxArticle.create_time >= today_start - timedelta(days=1),
            WxArticle.create_time <= today_end - timedelta(days=1)
        ).all()

        # 设置文件路径为 base_path/record.create_time(日期）-record.title/record.title.pdf
        result = {}
        for record in yesterday_records:
            sanitized_title = re.sub(r'[\\/:*?"<>|]', '', record.title)
            # 获取该记录的create_time
            parent_folder = f"{record.create_time.strftime('%Y-%m-%d')}-{sanitized_title}"
            file_path = os.path.join(
                base_path, parent_folder, f"{sanitized_title}.pdf")
            if os.path.exists(file_path):
                result[record.id] = file_path
            else:
                logger.info(f"文件不存在: {file_path}")

        # 生成文件路径
        return result
    except Exception as e:
        logger.info(f"查询记录失败: {e}")
        return {}


def get_today_file_paths(base_path):
    """
    获取 wx_article 表中今天创建的记录，返回以 id 为键，file_path 为值的字典。

    :param base_path: 基础路径，用于拼接生成文件路径
    :return: 一个字典 {id: file_path}
    """
    try:
        # 获取今天的日期范围
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=999999)
        today_date = datetime.now().strftime("%Y-%m-%d")  # 获取今天的日期字符串

        # 查询今天的记录
        records = session.query(WxArticle.id, WxArticle.title).filter(
            WxArticle.create_time >= today_start,
            WxArticle.create_time <= today_end
        ).all()

        # 生成文件路径字典
        result = {}
        for record in records:
            # 去除文件名中的非法字符
            sanitized_title = re.sub(r'[\\/:*?"<>|]', '', record.title)
            folder_name = f"{today_date}-{sanitized_title}"  # 父级文件夹命名
            file_path = os.path.join(
                base_path, folder_name, f"{sanitized_title}.pdf")  # 完整路径
            result[record.id] = file_path

        return result
    except Exception as e:
        logger.info(f"查询记录失败: {e}")
        return {}


def build_query_conditions(article_ids=None, article_type=None, accounts=None, only_today=False):
    """
    根据传入的参数动态构建查询条件。

    :param article_ids: 文章 ID 列表
    :param article_type: 文章类型（'general', 'recruitment', 'news', 'others'）
    :param accounts: 公众号账号 列表
    :param only_today: 是否仅查询今天创建的记录
    :return: 查询条件列表
    """
    conditions = []

    if article_ids:
        conditions.append(ProcessedArticle.id.in_(article_ids))

    if article_type:
        conditions.append(ProcessedArticle.article_type == article_type)

    if accounts is not None:
        if accounts:  # 非空列表才添加条件
            conditions.append(ProcessedArticle.account.in_(accounts))
        else:  # 空列表应该返回空结果
            conditions.append(ProcessedArticle.account.in_([]))  # 这会匹配不到任何记录

    if only_today:
        today_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_end = datetime.now().replace(
            hour=23, minute=59, second=59, microsecond=999999)
        conditions.append(ProcessedArticle.processed_time >= today_start)
        conditions.append(ProcessedArticle.processed_time <= today_end)

    return conditions


def fetch_processed_articles(query_conditions):
    """
    根据给定的查询条件从数据库中提取处理后的文章。

    :param query_conditions: 构建好的查询条件
    :return: 查询到的文章列表
    """
    try:
        articles = session.query(ProcessedArticle).filter(
            *query_conditions).order_by(
            ProcessedArticle.processed_time.desc(),
            ProcessedArticle.id.desc()
        ).all()
        if not articles:
            logger.info("未找到符合条件的文章！")
        return articles
    except Exception as e:
        logger.info(f"查询记录失败: {e}")
        return []


def fetch_processed_articles_by_id(article_ids, only_today=False):
    """
    根据 ID 查询处理后的文章记录。

    :param article_ids: 文章 ID 列表
    :param only_today: 是否仅查询今天创建的记录
    :return: 查询到的记录列表
    """
    query_conditions = build_query_conditions(
        article_ids=article_ids, only_today=only_today)
    return fetch_processed_articles(query_conditions)


def fetch_processed_articles_by_type(article_type, only_today=False):
    """
    根据文章类型查询处理后的文章记录。

    :param article_type: 文章类型（'general', 'recruitment', 'news', 'others'）
    :param only_today: 是否仅查询今天创建的记录
    :return: 查询到的记录列表
    """
    query_conditions = build_query_conditions(
        article_type=article_type, only_today=only_today)
    return fetch_processed_articles(query_conditions)


def fetch_processed_articles_by_accounts(accounts, only_today=False):
    """
    根据公众号账号查询处理后的文章记录。

    :param account: 公众号账号
    :param only_today: 是否仅查询今天创建的记录
    :return: 查询到的记录列表
    """
    query_conditions = build_query_conditions(
        accounts=accounts, only_today=only_today)
    return fetch_processed_articles(query_conditions)


def get_user_subscribed_accounts(email):
    email = (email or "").strip().lower()
    if not email:
        logger.info("No email provided when fetching subscribed accounts")
        return []

    # 1. 查找用户的user_id
    user = session.query(User).filter(func.lower(User.email) == email).first()

    if not user:
        logger.info(f"No user found with email {email}")
        return []

    # 用户 ID
    user_id = user.id

    # 2. 获取该用户订阅的标签
    subscribed_tags = session.query(UserTagSubscription.tag_id) \
        .filter(UserTagSubscription.user_id == user.id).all()

    # 2.2 获取与标签关联的公众号
    tag_related_accounts = []
    if subscribed_tags:
        tag_ids = [tag_id[0] for tag_id in subscribed_tags]
        if tag_ids:  # 如果用户有订阅标签
            tag_related_accounts = session.query(Account.account_name) \
                .join(AccountTag, AccountTag.account_id == Account.id) \
                .filter(AccountTag.tag_id.in_(tag_ids)) \
                .all()

    # 3. 获取直接订阅的公众号
    directly_subscribed_accounts = session.query(Account.account_name) \
        .join(UserSubscription, UserSubscription.account_id == Account.id) \
        .filter(UserSubscription.user_id == user_id) \
        .all()

    # 4. 合并两部分公众号并去重
    all_accounts = set(
        account.account_name for account in tag_related_accounts + directly_subscribed_accounts
    )

    # 返回结果
    if not all_accounts:
        logger.info(f"No accounts found for the user with email {email}.")
        return []

    return list(all_accounts)


def test_get_user_subscribed_accounts():
    """
    测试 get_user_subscribed_accounts 函数，验证查询结果是否符合预期。
    """
    # 测试查询用户订阅的公众号
    logger.info("测试查询用户订阅的公众号:")
    email = '1781051483@qq.com'
    accounts = get_user_subscribed_accounts(email)
    logger.info(f"用户 {email} 订阅的公众号: {accounts}, 共 {len(accounts)} 个")


def get_user_subscribed_accounts_processed_articles(email, only_today=True):
    """
    获取用户订阅的公众号的处理后的文章记录。

    :param email: 用户邮箱
    :return: 查询到的记录列表
    """
    # 1. 查找用户订阅的公众号
    accounts = get_user_subscribed_accounts(email)

    # 2. 查询处理后的文章记录
    query_conditions = build_query_conditions(
        accounts=accounts, only_today=only_today)
    articles = fetch_processed_articles(query_conditions)

    # 同一篇文章在一天内可能多次重跑，只保留最新记录，避免邮件混入旧摘要。
    unique_articles = []
    seen = set()
    for article in articles:
        if article.original_id is not None:
            dedupe_key = f"oid:{article.original_id}"
        elif article.content_url:
            dedupe_key = f"url:{article.content_url}"
        else:
            dedupe_key = f"title:{article.account}|{article.title}|{article.publish_date}"

        if dedupe_key in seen:
            continue

        seen.add(dedupe_key)
        unique_articles.append(article)

    return unique_articles


def test_get_user_subscribed_accounts_processed_articles():
    """
    测试 get_user_subscribed_accounts_processed_articles 函数，验证查询结果是否符合预期。
    """
    # 测试查询用户订阅的公众号的处理后的文章记录
    logger.info("测试查询用户订阅的公众号的处理后的文章记录:")
    # email = 'liuj@zjhyzc.com.cn'
    email = 'ziaoliu@hotmail.com'
    articles = get_user_subscribed_accounts_processed_articles(email)
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")


def test_fetch_processed_articles():
    """
    测试 fetch_processed_articles 函数，验证查询结果是否符合预期。
    """
    # 测试查询所有记录
    logger.info("测试查询所有记录:")
    articles = fetch_processed_articles([])
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询指定 ID 的记录
    logger.info("测试查询指定 ID 的记录:")
    articles = fetch_processed_articles_by_id([1, 2, 3])
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询指定类型的记录
    logger.info("测试查询指定类型的记录:")
    articles = fetch_processed_articles_by_type('recruitment', only_today=True)
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询指定公众号的记录
    logger.info("测试查询指定公众号的记录:")
    articles = fetch_processed_articles_by_accounts(['公众号A'])
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询今天的记录
    logger.info("测试查询今天的记录:")
    articles = fetch_processed_articles_by_id([], only_today=True)
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询指定类型且今天的记录
    logger.info("测试查询指定类型且今天的记录:")
    articles = fetch_processed_articles_by_type('recruitment', only_today=True)
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")

    # 测试查询指定公众号且今天的记录
    logger.info("测试查询指定公众号且今天的记录:")
    articles = fetch_processed_articles_by_accounts(['公众号A'], only_today=True)
    for article in articles:
        logger.info(f"ID: {article.id}, Title: {article.title}")


def test_get_today_file_paths():
    """
    测试 get_today_file_paths 函数，验证生成的文件路径是否符合预期。
    """
    # 定义基础路径
    base_path = r"D:\yy\wechatmonitor\output\airtleSave"

    try:
        # 调用函数获取结果
        # result = get_today_file_paths(base_path)

        result = get_today_and_yesterday_file_paths(base_path)

        # 打印结果
        logger.info("测试结果:")
        for article_id, file_path in result.items():
            logger.info(f"ID: {article_id}, File Path: {file_path}")

        # 验证结果是否非空
        if result:
            logger.info("测试通过: 生成的文件路径成功获取")
        else:
            logger.info("测试失败: 今天没有符合条件的记录")
    except Exception as e:
        logger.info(f"测试失败: {e}")


def test_update_processed_article():
    update_processed_article(1, '测试文章内容', 'content')
    update_processed_article(1, '测试文章摘要', 'processed_summary')
    update_processed_article(1, {'key': 'value'}, 'processed_key_info')

    # 测试更新不存在的记录
    update_processed_article(9999, '测试文章内容', 'content')


def test_reflect_database_info():
    # 创建元数据对象
    metadata = MetaData()

    # 反射整个数据库
    metadata.reflect(bind=engine)

    # 输出所有表的信息
    for table_name, table in metadata.tables.items():
        logger.info(f"\nTable: {table_name}")
        for column in table.columns:
            logger.info(
                f"  Column: {column.name}, Type: {column.type}, Primary Key: {column.primary_key}")

    # 如果需要外键关系
        for fk in table.foreign_keys:
            logger.info(
                f"  Foreign Key: {fk.column} references {fk.target_fullname}")


def get_or_create_user(name, email):
    """
    获取用户 ID，如果用户不存在则创建新用户。

    :param name: 用户名称
    :param email: 用户邮箱
    :return: 用户 ID
    """
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("email is required")

    user = session.query(User).filter(func.lower(User.email) == email).first()
    if user:
        # 如果用户存在，更新信息
        user.name = name
        user.email = email
        session.commit()
        logger.info(f"用户已更新: {email}")
    else:
        # 创建新用户
        user = User(name=name, email=email)
        session.add(user)
        session.commit()
        logger.info(f"新用户已创建: {email}")
    return user.id


def _normalize_subscribed_wechats(subscribed_wechats):
    if not subscribed_wechats:
        return []

    normalized = []
    seen = set()
    for wechat_name in subscribed_wechats:
        name = str(wechat_name or "").strip()
        if not name or name in seen:
            continue
        seen.add(name)
        normalized.append(name)
    return normalized


def handle_user_subscriptions(user_id, subscribed_wechats):
    """
    更新用户的账号订阅关系。

    :param user_id: 用户 ID
    :param subscribed_wechats: 用户订阅的公众号名称列表
    """
    desired_names = _normalize_subscribed_wechats(subscribed_wechats)

    existing_subscriptions = session.query(UserSubscription).filter_by(
        user_id=user_id).all()
    existing_account_ids = {subscription.account_id for subscription in existing_subscriptions}

    if not desired_names:
        for subscription in existing_subscriptions:
            session.delete(subscription)
        session.commit()
        logger.info(f"用户 {user_id} 无个性化订阅账号，已清空历史账号订阅")
        return

    desired_account_ids = set()
    for wechat_name in desired_names:
        # 检查公众号是否存在
        account = session.query(Account).filter_by(
            account_name=wechat_name).first()
        if not account:
            # 如果账号不存在，创建
            account = Account(account_name=wechat_name)
            session.add(account)
            session.commit()
            logger.info(f"新公众号已创建: {wechat_name}")

        desired_account_ids.add(account.id)

    for subscription in existing_subscriptions:
        if subscription.account_id not in desired_account_ids:
            session.delete(subscription)
            logger.info(f"用户 {user_id} 已取消公众号订阅: account_id={subscription.account_id}")

    for account_id in desired_account_ids - existing_account_ids:
        # 检查用户是否已订阅该账号
        new_subscription = UserSubscription(
            user_id=user_id, account_id=account_id)
        session.add(new_subscription)
        logger.info(f"用户 {user_id} 已订阅公众号: account_id={account_id}")

    session.commit()


def handle_recruitment_tag_subscription(user_id, need_recruitment, tag_id=1):
    """
    如果用户有招聘需求，为用户添加指定的标签订阅。

    :param user_id: 用户 ID
    :param need_recruitment: 是否需要招聘
    :param tag_id: 标签 ID（默认为 1 表示招聘标签）
    """
    # 检查是否已有订阅关系
    subscription = session.query(UserTagSubscription).filter_by(
        user_id=user_id, tag_id=tag_id).first()

    if need_recruitment:
        if not subscription:
            # 插入标签订阅
            new_subscription = UserTagSubscription(
                user_id=user_id, tag_id=tag_id)
            session.add(new_subscription)
            session.commit()
            logger.info(f"用户 {user_id} 已订阅招聘标签 (tag_id={tag_id})")
    else:
        # 用户退订
        if subscription:
            # 删除标签订阅
            session.delete(subscription)
            session.commit()
            logger.info(f"用户 {user_id} 已取消订阅招聘标签 (tag_id={tag_id})")


def process_user_info(name, email, need_recruitment, subscribed_wechats):
    """
    处理用户信息，更新或创建用户及其订阅关系。

    :param name: 用户名称
    :param email: 用户邮箱
    :param need_recruitment: 是否需要招聘
    :param subscribed_wechats: 用户订阅的公众号列表
    """
    try:
        # Step 1: 获取或创建用户
        user_id = get_or_create_user(name, email)

        if need_recruitment:
            # Step 2: 用户订阅时，按最新问卷内容覆盖账号订阅关系
            handle_user_subscriptions(user_id, subscribed_wechats)
            # Step 3: 更新招聘标签订阅
            handle_recruitment_tag_subscription(user_id, True)
        else:
            # 用户退订 Pandora 时，清空标签和个性化账号订阅，避免历史订阅继续发信。
            handle_user_subscriptions(user_id, [])
            handle_recruitment_tag_subscription(user_id, False)

        logger.info(f"成功处理用户: {email}")
    except Exception as e:
        session.rollback()
        logger.info(f"处理用户 {email} 时出错: {e}")


def process_user_batch(user_data):
    """
    批量处理用户信息。

    :param user_data: 用户信息列表，每个元素是一个字典
    """
    latest_users_by_email = {}
    for user in user_data:
        email = (getattr(user, "email", "") or "").strip().lower()
        if not email:
            logger.info("跳过无邮箱用户")
            continue
        user.email = email
        latest_users_by_email[email] = user

    for user in latest_users_by_email.values():
        process_user_info(
            name=user.name,
            email=user.email,
            need_recruitment=user.need_recruiment,
            subscribed_wechats=user.subscribed_wechats
        )


def fetch_unprocessed_articles(db_path=None, start_date=datetime.now().strftime('%Y-%m-%d'), end_date=datetime.now().strftime('%Y-%m-%d')):
    """获取未处理的文章"""
    if db_path is None:
        db_path = SQLITE_DB_PATH

    # 目标日期的开始和结束时间
    start_date = f"{start_date} 00:00:00"
    end_date = f"{end_date} 23:59:59"

    print(f"Fetching records from {start_date} to {end_date}")

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 直接使用日期字符串进行查询，按创建时间升序排列
    query = """
        SELECT id, title, content, url, account_name, created_at, pdf_path 
        FROM wechat_articles 
        WHERE pandora_processed = FALSE
        AND created_at >= ? 
        AND created_at <= ?
        ORDER BY created_at ASC
    """
    cursor.execute(query, (start_date, end_date))

    articles = [dict(zip(['id', 'title', 'content', 'url', 'account', 'publish_date', 'pdf_path'], row))
                for row in cursor.fetchall()]
    conn.close()

    return articles


def mark_article_processed(article_id, db_path=None):
    """标记文章为已处理"""
    if db_path is None:
        db_path = SQLITE_DB_PATH
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE wechat_articles 
        SET pandora_processed = TRUE 
        WHERE id = ?
    """, (article_id,))
    conn.commit()
    conn.close()


def update_article_type(article_id, article_type):
    """
    更新文章的类型字段。

    :param article_id: 文章ID
    :param article_type: 文章类型 ('recruitment', 'news', 'others', 'general')
    :return: 更新是否成功
    """
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()

        # 更新文章类型
        update_query = """
        UPDATE wechat_articles 
        SET article_type = ?, 
            process_time = CURRENT_TIMESTAMP
        WHERE id = ?
        """
        cursor.execute(update_query, (article_type, article_id))

        # 提交更改
        conn.commit()

        # 检查是否有记录被更新
        if cursor.rowcount > 0:
            logger.info(f"成功更新文章类型: ID = {article_id}, 类型 = {article_type}")
            success = True
        else:
            logger.info(f"更新失败: 找不到 ID = {article_id} 的记录")
            success = False

        cursor.close()
        conn.close()
        return success

    except Exception as e:
        logger.info(f"更新文章类型失败: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return False


def batch_update_article_types(articles_data):
    """
    批量更新多篇文章的类型。

    :param articles_data: 包含文章ID和类型的列表，格式为 [(id, type), ...]
    :return: 成功更新的记录数
    """
    try:
        conn = sqlite3.connect(SQLITE_DB_PATH)
        cursor = conn.cursor()

        # 批量更新文章类型
        update_query = """
        UPDATE wechat_articles 
        SET article_type = ?,
            process_time = CURRENT_TIMESTAMP
        WHERE id = ?
        """

        # 执行批量更新
        cursor.executemany(update_query, [(type_, id_)
                           for id_, type_ in articles_data])

        # 提交更改
        conn.commit()
        updated_count = cursor.rowcount

        logger.info(f"成功更新 {updated_count} 篇文章的类型")

        cursor.close()
        conn.close()
        return updated_count

    except Exception as e:
        logger.info(f"批量更新文章类型失败: {e}")
        if 'conn' in locals():
            conn.rollback()
            conn.close()
        return 0


def fetch_articles_by_type(article_type, only_today=False, db_path=None):
    """
    从 wechat_articles 表中查询指定类型的文章。

    :param article_type: 文章类型 ('recruitment', 'news', 'others', 'general')
    :param only_today: 是否只查询今天的文章
    :param db_path: 数据库路径
    :return: 文章列表，每个文章是一个字典，包含文章的各个字段
    """
    if db_path is None:
        db_path = SQLITE_DB_PATH

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 构建基础查询
        query = """
            SELECT id, title, content, url, account_name, created_at, pdf_path, article_type, summary
            FROM wechat_articles 
            WHERE article_type = ?
            AND pandora_processed = TRUE
        """

        # 如果只查询今天处理的文章，添加日期条件
        if only_today:
            query += " AND DATE(process_time) = DATE('now')"

        # 执行查询
        cursor.execute(query, (article_type,))

        # 将查询结果转换为字典列表
        columns = ['id', 'title', 'content', 'url', 'account',
                   'publish_date', 'pdf_path', 'article_type', 'summary']
        articles = [dict(zip(columns, row)) for row in cursor.fetchall()]

        cursor.close()
        conn.close()

        logger.info(f"成功查询到 {len(articles)} 篇{article_type}类型的文章")
        return articles

    except Exception as e:
        logger.info(f"查询文章失败: {e}")
        if 'conn' in locals():
            conn.close()
        return []


def create_tables():
    """创建所有必要的数据库表"""
    try:
        Base.metadata.create_all(engine)
        logger.info("成功创建所有数据库表")
    except Exception as e:
        logger.error(f"创建数据库表失败: {e}")


# 本地 sqlite 后端：模块加载时幂等建表（users/accounts/subscriptions/processed_articles 等）
create_tables()


def import_accounts_with_tag(source_file, tag_id=1):
    """
    从文本文件导入公众号列表并打上指定标签。
    使用 SQLAlchemy ORM 方式处理数据库操作。

    :param source_file: 包含公众号列表的文本文件路径
    :param tag_id: 要添加的标签ID，默认为1（招聘标签）
    :return: 成功导入的公众号数量
    """
    try:
        # 读取公众号列表
        with open(source_file, 'r', encoding='utf-8') as f:
            accounts = [line.strip() for line in f if line.strip()]

        # 计数器
        imported_count = 0
        tagged_count = 0

        for account_name in accounts:
            try:
                # 1. 检查公众号是否存在
                account = session.query(Account).filter_by(
                    account_name=account_name).first()

                if not account:
                    # 如果账号不存在，创建
                    account = Account(account_name=account_name)
                    session.add(account)
                    session.commit()
                    logger.info(f"新公众号已创建: {account_name}")
                    imported_count += 1

                # 2. 检查标签关联是否存在
                tag_exists = session.query(AccountTag).filter_by(
                    account_id=account.id, tag_id=tag_id).first()

                if not tag_exists:
                    # 创建标签关联
                    new_tag = AccountTag(account_id=account.id, tag_id=tag_id)
                    session.add(new_tag)
                    session.commit()
                    logger.info(f"公众号 {account_name} 已添加招聘标签")
                    tagged_count += 1

            except Exception as e:
                session.rollback()
                logger.error(f"处理公众号 {account_name} 时出错: {e}")
                continue

        logger.info(
            f"导入完成: 成功导入 {imported_count} 个公众号，新增 {tagged_count} 个标签关联")
        return imported_count

    except Exception as e:
        session.rollback()
        logger.error(f"导入公众号失败: {e}")
        return 0


def test_import_accounts():
    """测试导入公众号和标签关联的函数"""
    source_file = os.getenv(
        "RECRUITMENT_SOURCE_FILE",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "source", "招聘公众号信源.txt"),
    )
    imported_count = import_accounts_with_tag(source_file, tag_id=1)
    logger.info(f"测试导入结果: 成功导入 {imported_count} 个公众号")


def get_all_user_subscriptions():
    """
    获取所有用户的订阅信息。

    :return: 一个字典，键是用户邮箱，值是该用户订阅的公众号列表。
    """
    all_subscriptions = {}
    try:
        # 1. 获取所有用户
        all_users = session.query(User).all()

        if not all_users:
            logger.info("数据库中没有找到任何用户。")
            return {}

        # 2. 遍历每个用户，获取其订阅的公众号
        for user in all_users:
            # 复用已有的函数来获取每个用户的订阅列表
            subscribed_accounts = get_user_subscribed_accounts(user.email)
            # 仅记录存在订阅关系的用户
            if subscribed_accounts:
                all_subscriptions[user.email] = subscribed_accounts

        return all_subscriptions

    except Exception as e:
        logger.error(f"获取所有用户订阅信息时出错: {e}")
        return {}


def test_show_all_user_subscriptions():
    """
    测试函数，用于显示所有用户的订阅列表。
    """
    logger.info("开始测试：显示所有用户的订阅信息...")

    # 调用核心逻辑函数获取数据
    all_subscriptions = get_all_user_subscriptions()

    if not all_subscriptions:
        logger.info("数据库中没有找到任何用户的订阅信息。")
        return

    logger.info("---------- 用户订阅列表 ----------")
    # 遍历字典并格式化输出
    for email, accounts in all_subscriptions.items():
        logger.info(f"用户: {email}")
        logger.info(f"  订阅的公众号 ({len(accounts)}个):")
        # 对公众号列表进行排序，使输出更整洁
        for account in sorted(accounts):
            logger.info(f"    - {account}")
        logger.info("-" * 30)  # 分隔符

    logger.info("---------- 测试结束 ----------")


if __name__ == '__main__':
    try:
        # logger.info("创建数据库表...")
        # create_tables()

        # logger.info("测试数据库连接...")
        # test_reflect_database_info()

        # logger.info("测试导入公众号...")
        # test_import_accounts()

        # logger.info("\n数据库连接测试完成！")

        # logger.info("测试获取用户订阅的公众号...")
        # test_get_user_subscribed_accounts_processed_articles()

        # 测试获取所有用户的订阅信息
        test_show_all_user_subscriptions()

    except Exception as e:
        logger.error(f"数据库连接测试失败: {e}")
