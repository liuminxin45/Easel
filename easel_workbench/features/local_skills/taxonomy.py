"""Reviewed categories and Chinese labels; contains no third-party skill text."""
import re

CATEGORIES={
 'research':('发现与资料','discover'), 'planning':('选题与内容策略','plan'),
 'writing':('写作与叙事','produce'), 'voice':('文风与人格','produce'),
 'polish':('润色与去 AI 味','produce'), 'review':('审稿与事实核查','produce'),
 'title':('标题与短文案','produce'), 'layout':('排版与格式','produce'),
 'image':('封面、配图与卡片','produce'), 'video':('视频与音频','produce'),
 'publish':('草稿与发布工具','publish'), 'analytics':('数据分析与复盘','attribute'),
 'tools':('索引与通用工具','general')}
STAGES={'writing':'写作方法','research':'资料研究','polish':'润色','review':'审稿','layout':'排版','cover':'封面','illustration':'正文配图'}
LABELS={
 'human-writing':'活人感写作','khazix-writer':'卡兹克写作','humanizer':'英文去 AI 味',
 'humanizer-zh':'中文去 AI 味','humanizer-zh-next':'中文去 AI 味进阶','nuwa-skill':'女娲·表达视角',
 'Viral_Writer_Skill':'内容洞见写作','writing-assistant-skill':'自媒体写作助手',
 'gzh-design-skill':'甲木公众号排版','guizang-social-card-skill':'归藏社交卡片',
 'zh-tech-writing':'中文技术写作','md2wechat':'公众号 Markdown 排版',
 'wewrite':'WeWrite 全流程','wewrite-write':'WeWrite 文章初稿','wewrite-review':'WeWrite 编辑审稿',
 'wewrite-rewrite':'WeWrite 文章改写','wewrite-topic':'WeWrite 选题','wewrite-style':'WeWrite 文风',
 'wewrite-learn':'WeWrite 改稿分析','wewrite-visual':'WeWrite 配图','wewrite-stats':'WeWrite 数据分析',
 'wewrite-publish':'WeWrite 草稿发布','baoyu-article-illustrator':'宝玉文章配图',
 'baoyu-cover-image':'宝玉封面设计','baoyu-format-markdown':'宝玉 Markdown 整理',
 'baoyu-markdown-to-html':'宝玉 Markdown 转 HTML','baoyu-post-to-wechat':'宝玉公众号发布',
 'baoyu-image-gen':'宝玉图像生成','baoyu-infographic':'宝玉信息图','baoyu-xhs-images':'宝玉小红书卡片',
 'baoyu-comic':'宝玉漫画','baoyu-slide-deck':'宝玉演示文稿','baoyu-translate':'宝玉翻译',
 'post-writer':'社媒正文写作','post-formatter':'社媒成稿排版','hook-generator':'开头钩子',
 'hook-writer':'开头钩子写作','voice-builder':'作者声音构建','newsletter-voice':'通讯写作风格',
 'writing-style-and-tone':'写作文风与语气','storytelling-and-narrative':'故事与叙事',
 'content-research-and-sourcing':'内容研究与来源','caption-writer':'配文写作',
 'carousel-writer':'轮播卡片写作','thread-writer':'串文写作','image-prompt':'配图提示词',
 'infographic-and-data-viz':'信息图与数据可视化','quote-cards-and-text-graphics':'金句与文字卡片',
 'social-media-skill-finder':'社媒技能索引','wechat-article-publisher':'公众号文章发布',
 'writing-assistant':'自媒体写作助手','viral-writer':'内容洞见写作','gzh-design':'甲木公众号排版',
 'aihot':'AIHOT 中文 AI 资讯','hv-analysis':'卡兹克横纵分析','leader':'Agent 目标任务书',
 'neat-freak':'项目知识与规范整理','storage-analyzer':'磁盘空间分析',
 'baoyu-compress-image':'宝玉图片压缩','baoyu-danger-gemini-web':'宝玉 Gemini 网页生成',
 'baoyu-danger-x-to-markdown':'宝玉 X 内容转 Markdown','baoyu-diagram':'宝玉关系图设计',
 'baoyu-electron-extract':'宝玉桌面应用内容提取','baoyu-post-to-weibo':'宝玉微博发布',
 'baoyu-post-to-x':'宝玉 X 发布','baoyu-url-to-markdown':'宝玉网页转 Markdown',
 'baoyu-wechat-summary':'宝玉公众号摘要','baoyu-youtube-transcript':'宝玉 YouTube 字幕提取',
 'release-skills':'技能仓库版本发布工具','baoyu-slide-deck':'宝玉演示文稿',
 'aws-wechat-article-assets':'公众号参考素材整理','aws-wechat-article-formatting':'公众号文章排版',
 'aws-wechat-article-images':'公众号文章配图','aws-wechat-article-main':'公众号文章完整流程',
 'aws-wechat-article-publish':'公众号文章草稿发布','aws-wechat-article-review':'公众号文章审稿',
 'aws-wechat-article-topics':'公众号选题研究','aws-wechat-article-writing':'公众号文章写作',
 'aws-wechat-sticker':'公众号贴图制作',
 'analytics-dashboard':'社媒数据看板','content-matrix':'内容矩阵策划',
 'gemini-carousel':'Gemini 轮播卡片','gemini-infographic':'Gemini 信息图',
 'graphic-designer':'社媒视觉设计','niche-research':'细分领域研究','pinned-comment':'置顶评论写作',
 'post-scorer':'社媒稿件评分','profile-optimizer':'主页画像优化','quote-post':'引用短帖写作',
 'reels-scripting':'短视频脚本写作','youtube-thumbnail':'YouTube 封面',
 'creator-buddy':'创作者助手总入口','space-xhs-account-audit':'小红书账号诊断',
 'space-xhs-buddy':'小红书创作总入口','space-xhs-cover':'小红书封面',
 'space-xhs-hotspot':'小红书热点研究','space-xhs-image':'小红书配图',
 'space-xhs-note-analytics':'小红书笔记分析','space-xhs-positioning':'小红书内容定位',
 'space-xhs-title':'小红书标题','space-xhs-writer':'小红书正文写作','xhs-html':'小红书 HTML 卡片',
 'space-video':'视频制作流程','space-video-audio':'视频音频处理','space-video-broll':'视频补充镜头',
 'space-video-broll-sketch':'视频镜头草图','space-video-cover':'视频封面',
 'space-video-edit':'视频剪辑','space-video-script':'视频脚本','space-video-subtitle':'视频字幕',
 'space-video-topic':'视频选题','space-video-transcript':'视频转写',
 'baokuan-article-analysis':'公众号热门文章分析','baokuan-title-generator':'公众号标题设计',
 'global-content-search':'全网内容搜索','gzh-explosive-content-detector':'公众号热门文章发现',
 'gzh-longform-writer':'公众号长文写作','gzh-positioning':'公众号内容定位',
 'gzh-short-post':'公众号短文写作','space-chart-image':'数据图表配图','space-gzh-cover':'公众号封面',
 'space-text-logic-diagram':'文字逻辑关系图','space-wechat-layout':'公众号文章排版',
 'xiaohongshu-search':'小红书搜索','redbookskills':'小红书内容与账号工具',
 'social-push':'社交平台推送','self-media-content-workflow':'自媒体内容工作流',
 'awesome-social-media-skills':'自媒体技能索引','wechat-publisher':'公众号写作与发布流程',
 'wechat-article-publisher-skill':'公众号文章发布','md2wechat-skill':'公众号 Markdown 排版',
 'social-media-skills':'社交媒体技能集','skills':'社交媒体技能索引'}
WORDS={'article':'文章','writer':'写作','writing':'写作','wechat':'公众号','gzh':'公众号','xhs':'小红书',
 'xiaohongshu':'小红书','title':'标题','cover':'封面','image':'图像','note':'笔记','review':'审稿',
 'topic':'选题','planner':'策划','content':'内容','strategy':'策略','social':'社媒','media':'媒体',
 'voice':'声音','style':'文风','tone':'语气','profile':'画像','brand':'品牌','research':'研究',
 'search':'搜索','global':'全网','hotspot':'热点','hotnotes':'热门笔记','analytics':'分析',
 'analysis':'分析','performance':'效果','publish':'发布','publisher':'发布','formatting':'排版',
 'layout':'排版','short':'短篇','longform':'长文','script':'脚本','video':'视频','audio':'音频',
 'rewrite':'改写','learn':'学习分析','stats':'统计','assets':'素材','main':'主流程','suite':'工具集',
 'assistant':'助手','skill':'技能','skills':'技能集','builder':'构建','perspective':'视角',
 'optimization':'优化','seo':'搜索优化','framework':'框架','novelists':'小说创作','novel':'小说',
 'engagement':'互动','community':'社群','reply':'回复','comment':'评论','calendar':'日历',
 'plan':'计划','repurposer':'改编','repurposing':'改编','scorer':'评分','scoring':'评分',
 'audience':'受众','competitor':'竞品','positioning':'定位','conversion':'转化','path':'路径',
 'human':'活人感','humanizer':'去 AI 味','zh':'中文','next':'进阶','en':'英文','translate':'翻译',
 'translation':'翻译','newsletter':'通讯','storytelling':'故事表达','narrative':'叙事',
 'sourcing':'来源查证','format':'排版','formatter':'排版','post':'短帖','posts':'短帖',
 'hook':'开头钩子','generator':'生成','generation':'生成','prompt':'提示词','craft':'创作',
 'toneofvoice':'表达语气','editing':'编辑','editor':'编辑','edit':'修改','copy':'文案',
 'copywriting':'文案写作','proofreading':'校对','proofreader':'校对','fact':'事实',
 'checking':'核查','check':'检查','quality':'质量','assurance':'核验','researcher':'研究',
 'linkedin':'领英','instagram':'Instagram','facebook':'Facebook','twitter':'X',
 'tiktok':'TikTok','youtube':'YouTube','pinterest':'Pinterest','reddit':'Reddit',
 'threads':'Threads','bluesky':'Bluesky','substack':'Substack','mastodon':'Mastodon',
 'business':'业务','personal':'个人','bio':'简介','about':'介绍','page':'页面','pages':'页面',
 'creation':'创作','creative':'创意','idea':'灵感','ideas':'灵感','ideation':'创意构思',
 'engaging':'互动','growth':'增长','audit':'诊断','tracking':'追踪','insights':'洞察',
 'insight':'洞察','metrics':'指标','report':'报告','reporting':'报告','dashboard':'看板',
 'competitive':'竞品','intelligence':'情报','discovery':'发现','discover':'发现',
 'distribution':'分发','scheduling':'排期','schedule':'排期','platform':'平台',
 'platforms':'平台','cross':'跨','multi':'多','channel':'渠道','channels':'渠道',
 'engagements':'互动','response':'回应','responses':'回应','comments':'评论',
 'repurpose':'改编','recycling':'复用','recycle':'复用','reuse':'复用','adapt':'改编',
 'adaptation':'改编','curation':'精选整理','curator':'精选整理','curate':'精选整理',
 'branding':'品牌','campaign':'活动','campaigns':'活动','launch':'上线',
 'product':'产品','launches':'发布活动','ads':'广告','ad':'广告','advertising':'广告',
 'advertisement':'广告','paid':'付费','organic':'自然增长','funnel':'转化路径',
 'leads':'线索','lead':'线索','prospect':'潜在受众','outreach':'联系',
 'community':'社群','management':'管理','manager':'管理','listening':'舆情观察',
 'monitoring':'监测','monitor':'监测','sentiment':'情绪','crisis':'危机',
 'hashtags':'话题标签','hashtag':'话题标签','keyword':'关键词','keywords':'关键词',
 'visual':'视觉','design':'设计','designer':'设计','graphic':'图形','graphics':'图形',
 'infographic':'信息图','carousel':'轮播卡片','carousels':'轮播卡片','reels':'短视频',
 'reel':'短视频','thumbnail':'封面','thumbnails':'封面','sticker':'贴图',
 'captions':'配文','caption':'配文','quote':'引用','quotes':'金句','text':'文字',
 'cards':'卡片','card':'卡片','images':'图像','illustration':'配图','illustrator':'配图',
 'diagram':'关系图','data':'数据','viz':'可视化','chart':'图表','charts':'图表',
 'and':'与','to':'转','from':'来自','for':'面向','of':'的','with':'结合',
 'ai':'AI','seo':'搜索优化','sms':'社媒','buddy':'助手','baoyu':'宝玉','khazix':'卡兹克'}

# Exceptions describe this skill, never every child in a similarly named repo.
KINDS={
 'human-writing':'writing','khazix-writer':'writing','writing-assistant':'writing',
 'writing-assistant-skill':'writing','viral-writer':'writing','viral-writer-skill':'writing',
 'aihot':'research','hv-analysis':'research','leader':'tools','neat-freak':'tools',
 'storage-analyzer':'tools','release-skills':'tools','creator-buddy':'tools',
 'space-xhs-buddy':'tools','aws-wechat-article-main':'writing','aws-wechat-article-assets':'research',
 'aws-wechat-sticker':'image','baoyu-translate':'writing','baoyu-slide-deck':'image',
 'baoyu-compress-image':'tools','baoyu-url-to-markdown':'research',
 'baoyu-danger-x-to-markdown':'research','baoyu-electron-extract':'research',
 'baoyu-youtube-transcript':'research','baoyu-wechat-summary':'research',
 'space-xhs-account-audit':'analytics','baokuan-article-analysis':'research',
 'gzh-explosive-content-detector':'research','space-video-topic':'planning',
 'space-video-script':'video','space-video-transcript':'research',
 'wewrite-learn':'analytics','wewrite':'writing','wechat-publisher':'writing',
 'social-media-skill-finder':'tools','awesome-social-media-skills':'tools',
 'social-media-skills':'tools','skills':'tools','redbookskills':'tools',
 'self-media-content-workflow':'tools','social-push':'publish'}

# Full workflow entrypoints remain runnable on their own, not a second main
# workflow nested inside an Oil Pig production turn.
STANDALONE={'wewrite','aws-wechat-article-main','wechat-publisher','creator-buddy',
            'space-xhs-buddy','redbookskills','self-media-content-workflow',
            'baoyu-slide-deck','baoyu-compress-image','release-skills'}

# Names reviewed against the imported entrypoints. These concise labels are
# presentation metadata, not translated copies of the third-party instructions.
SOCIAL_LABELS={
 'research':{
  'audience-research':'社媒受众研究','competitor-analysis':'社媒竞品分析',
  'content-research-and-sourcing':'内容研究与来源核查','data-and-original-research':'数据与原创研究',
  'trend-jacking':'热点借势研究','viral-reverse-engineering':'热门内容拆解',
  'self-media-trend-radar':'自媒体热点与竞品研究'},
 'planning':{
  'ai-search-optimization':'AI 搜索可见性优化','batch-content-plan':'批量内容策划',
  'brand-profile':'品牌画像','campaign-and-launch-planning':'活动与产品发布策划',
  'collabs-and-cross-promotion':'创作者合作与交叉推广','community-management':'社群经营',
  'content-calendar':'内容日历','content-pillars':'内容栏目规划',
  'creator-monetization':'创作者收入规划','crisis-and-moderation':'社媒危机与社区管理',
  'email-and-newsletter':'邮件与通讯策略','engagement-routine':'日常互动计划',
  'facebook-groups':'Facebook 社群策略','facebook-strategy':'Facebook 内容策略',
  'hashtag-strategy':'话题标签策略','idea-generation-and-ideation':'选题灵感生成',
  'instagram-growth':'Instagram 增长策略','instagram-seo':'Instagram 搜索优化',
  'lead-magnets-and-funnels':'线索收集与转化路径','link-in-bio-and-traffic':'主页链接与流量转化',
  'linkedin-company-pages':'领英公司主页策略','linkedin-growth':'领英个人增长策略',
  'pinterest-growth':'Pinterest 增长策略','pinterest-seo':'Pinterest 搜索优化',
  'profile-optimization':'社媒主页优化','reddit-marketing':'Reddit 内容策略',
  'seasonal-and-moment-marketing':'节日与时间节点策划','social-selling-and-dm':'社媒私信转化策略',
  'social-seo':'社媒搜索优化','social-strategy':'社媒整体策略','threads-growth':'Threads 增长策略',
  'tiktok-growth':'TikTok 增长策略','ugc-and-influencer':'用户内容与创作者合作',
  'x-growth':'X 增长策略','youtube-long-form':'YouTube 长视频策略','youtube-shorts':'YouTube 短视频策略',
  'content-calendar-sms':'内容日历','content-strategy-sms':'社媒内容策略',
  'optimization-advisor-sms':'社媒内容优化建议','platform-strategy-sms':'分平台内容策略',
  'social-media-context-sms':'社媒画像与创作背景','self-media-content-brief':'自媒体创作简报',
  'self-media-content-strategy':'自媒体内容策略'},
 'writing':{
  'before-after-and-transformation':'前后对比与变化叙事','behind-the-scenes-and-founder':'幕后与创始人故事',
  'carousel-writer':'轮播卡片文案','content-recycling':'历史内容改编复用',
  'contrarian-and-opinion':'观点与反常识写作','cross-platform-repurposing':'跨平台内容改编',
  'educational-content-and-how-to':'知识讲解与教程写作','interactive-content':'互动内容设计',
  'linkedin-post-writer':'领英短帖写作','listicle-and-roundup':'清单与合集写作',
  'meme-and-culture':'网络文化与梗内容','social-proof-and-testimonials':'真实案例与用户评价写作',
  'story-writer':'社媒限时动态写作','storytelling-and-narrative':'故事与叙事写作',
  'text-post-and-microblog':'短文与微博客写作','thread-writer':'串文写作','threads-post':'Threads 短帖写作',
  'carousel-writer-sms':'轮播卡片文案','content-repurposer-sms':'内容多形式改编',
  'post-writer-sms':'社媒正文写作','thread-writer-sms':'串文写作',
  'self-media-platform-copywriting':'自媒体分平台文案'},
 'title':{
  'caption-writer':'社媒配文写作','hook-writer':'开头钩子写作','reply-and-comment-writer':'回复与评论写作',
  'caption-writer-sms':'社媒配文写作','hook-writer-sms':'开头钩子写作'},
 'voice':{
  'voice-builder':'作者声音构建','writing-style-and-tone':'写作文风与语气'},
 'review':{
  'platform-specs-and-validation':'平台格式规范与成稿核查'},
 'image':{
  'ai-image-editing':'AI 图像编辑','canva':'Canva 视觉设计','design-and-templates':'视觉设计与模板',
  'flux':'FLUX 图像生成','ideogram':'Ideogram 图像提示词','image-prompt':'图像提示词设计',
  'infographic-and-data-viz':'信息图与数据可视化','nano-banana':'Nano Banana 图像提示词',
  'pinterest-pin-design':'Pinterest 图片设计','quote-cards-and-text-graphics':'金句与文字卡片',
  'thumbnail-design':'YouTube 封面设计','tiktok-photo-mode':'TikTok 图片轮播',
  'xiaohongshu-magazine':'小红书杂志卡片'},
 'video':{
  'ai-music-and-sound':'AI 音乐与音效','ai-video':'AI 视频制作','ai-voiceover':'AI 旁白配音',
  'capcut':'剪映短视频制作','captions-and-clipping':'视频字幕与片段剪辑',
  'descript':'Descript 音视频编辑','heygen':'HeyGen 数字人视频','kling':'可灵视频制作',
  'livestream-and-realtime':'直播与实时内容','luma':'Luma 视频镜头',
  'opus-clip':'OpusClip 长视频切片','podcast-and-audiograms':'播客音频与声音卡片',
  'reels-script':'Instagram 短视频脚本','runway':'Runway 视频制作',
  'scripting-and-storyboarding':'视频脚本与分镜','short-form-video-script':'竖屏短视频脚本',
  'suno':'Suno 音乐创作','synthesia':'Synthesia 数字人视频',
  'talking-head-and-piece-to-camera':'真人口播与出镜表达','tiktok-script':'TikTok 视频脚本',
  'veo-3':'Veo 视频提示词','self-media-short-video':'自媒体短视频方案'},
 'publish':{
  'instagram-reels-publishing':'Instagram 短视频发布','scheduling-and-queue':'社媒内容排期与发布',
  'tiktok-video-publishing':'TikTok 视频发布','youtube-publishing-and-metadata':'YouTube 发布与元数据',
  'self-media-video-publisher':'自媒体视频发布','self-media-wechat-publisher':'自媒体公众号排版与草稿'},
 'analytics':{
  'analytics-and-reporting':'社媒数据分析与报告','content-audit':'社媒历史内容审计',
  'experimentation-and-ab-testing':'社媒内容 A/B 测试','goals-and-kpis':'社媒目标与成效指标',
  'audience-growth-tracker-sms':'受众增长追踪','content-pattern-analyzer-sms':'高效内容规律分析',
  'performance-analyzer-sms':'社媒内容表现分析','self-media-content-analytics':'自媒体数据复盘'},
 'tools':{'self-media-content-delivery':'自媒体版本与交付整理','agent-browser':'Agent 浏览器工具'}
}
for category, entries in SOCIAL_LABELS.items():
 LABELS.update(entries)
 KINDS.update({name:category for name in entries})
STANDALONE.update({'self-media-content-delivery','brand-profile','social-media-context-sms'})


def normalized(value):
 return re.sub(r'[\s_]+','-',str(value).strip()).lower()


def without_version(value):
 """Hide release suffixes in display names; source name/path stay untouched."""
 return re.sub(r'(?:[\s._·-]+|^)[vV]\d+(?:\.\d+)*(?=$|[\s._·-])','',value).strip(' ._·-')


def classify(repo,path,meta):
 folder=path.split('/')[-2] if '/' in path else repo.split('/')[-1]
 original=str(meta.get('name') or folder).strip()
 name=normalized(without_version(original))
 folder_name=normalized(without_version(folder))
 # Repository names such as wechat-publisher do not describe a nested writer,
 # reviewer or researcher. Only the selected entry's own identity participates.
 raw=name+' '+folder_name
 patterns=[('publish',r'publish|social-push|scheduling|queue'),('analytics',r'analytic|stats|performance|tracker|postmortem'),
 ('polish',r'humaniz|polish|rewrite|revision'),('review',r'review|scor|eval|validation|fact.check'),
 ('layout',r'format|layout|md2wechat|gzh-design|markdown.to.html|doc.convert'),
 ('image',r'cover|image|card|visual|infographic|illustrat|diagram|graphic|thumbnail|comic|gemini|sticker'),
 ('video',r'video|audio|voiceover|reels|podcast|music|script|subtitle|clip|suno|kling|runway|veo|heygen'),
 ('title',r'title|hook|caption|quote.post|pinned.comment'),('research',r'research|search|hot|radar|sourc|trend|competitor|curat'),
 ('planning',r'plan|strateg|matrix|position|brief|calendar|audience|profile|brand|topic|ideation'),
 ('voice',r'persona|perspective|voice|style|nuwa|novelists|zimeiti'),
 ('writing',r'writ|post|article|story|thread|copy|content|novel')]
 category=(KINDS.get(name) or next((key for key,pattern in patterns if re.search(pattern,name)),None)
           or KINDS.get(folder_name) or next((key for key,pattern in patterns if re.search(pattern,folder_name)),'tools'))
 if repo.lower() in ('momozi1996/awesome-ai-persona-skills','alchaincyf/nuwa-skill'):
  category='voice'
 labels={normalized(key):value for key,value in LABELS.items()}
 label=labels.get(name) or labels.get(folder_name)
 if not label:
  words=re.split('[-_]+',re.sub(r'^(aws-wechat-|self-media-|space-|sms-)','',name))
  label='·'.join(WORDS.get(word.lower(),word) for word in words)
 label=without_version(label)
 if not re.search('[\u4e00-\u9fff]',label):label=CATEGORIES[category][0]+'·'+label
 stages=[]
 if category in ('writing','voice','title'):stages=['writing']
 elif category in ('research','planning'):stages=['research']
 elif category in ('polish','review','layout'):stages=[category]
 elif category=='image':stages=['cover'] if 'cover' in raw or 'thumbnail' in raw else ['illustration']
 if name in STANDALONE or folder_name in STANDALONE:stages=[]
 return {'display_name':'油猪·'+label,'category':category,'category_label':CATEGORIES[category][0],
         'layer':CATEGORIES[category][1],'stages':stages,'tags':[original,folder,repo,CATEGORIES[category][0]],
         'description':str(meta.get('description','')).strip()[:240]}
