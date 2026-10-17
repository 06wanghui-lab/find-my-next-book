import { useState } from "react";
import type { FormEvent } from "react";

import { RecommendationApiError, requestRecommendations } from "./api";
import type { RecommendationResponse, VerificationStatus } from "./api";

const examples = [
  "想看女频仙侠，女主成长线强，不要虐恋",
  "类似《诡秘之主》的世界观，但希望已经完结",
  "轻松甜文，双向暗恋，不要娱乐圈",
];

const verificationLabels: Record<VerificationStatus, string> = {
  official: "官方页面已确认",
  corroborated: "多来源印证",
  unverified: "信息待核实",
};

const publicationLabels = {
  completed: "已完结",
  ongoing: "连载中",
  unknown: "状态待确认",
};

const reasonKindLabels = {
  verified_metadata: "已核实",
  attributed_reader_opinion: "读者评价",
  preference_inference: "口味匹配",
};

export function App() {
  const [request, setRequest] = useState("");
  const [result, setResult] = useState<RecommendationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const normalizedRequest = request.trim();
    if (normalizedRequest.length < 3) {
      setError("请多写一点你的阅读偏好，我们才能开始寻找。");
      return;
    }

    setIsLoading(true);
    setError(null);
    setResult(null);
    try {
      setResult(await requestRecommendations(normalizedRequest));
    } catch (reason) {
      setError(
        reason instanceof RecommendationApiError
          ? reason.message
          : "发生了意外错误，请稍后再试。",
      );
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <main className="page-shell">
      <header className="site-header">
        <a className="wordmark" href="#top" aria-label="NovelScout 首页">
          <span aria-hidden="true">阅</span>
          NovelScout
        </a>
        <p>真实书目 · 来源可查 · 为你排序</p>
      </header>

      <section className="hero" id="top" aria-labelledby="page-title">
        <div className="hero-copy">
          <p className="eyebrow">FIND MY NEXT BOOK · 小说侦察员</p>
          <h1 id="page-title">下一本喜欢的小说，从一句话开始。</h1>
          <p className="intro">
            说说你喜欢的题材、角色、氛围和雷点。NovelScout 会搜索真实书目、核对来源，
            再解释每一本为什么可能适合你。
          </p>

          <form className="discovery-form" onSubmit={handleSubmit} aria-busy={isLoading}>
            <label htmlFor="preferences">今天想读什么？</label>
            <textarea
              id="preferences"
              name="preferences"
              placeholder="例如：喜欢《我在无限游戏里封神》的烧脑副本和群像，想看类似的 BL 无限流，但不要感情线盖过剧情……"
              rows={5}
              value={request}
              onChange={(event) => setRequest(event.target.value)}
              disabled={isLoading}
            />
            <button type="submit" disabled={isLoading}>
              {isLoading ? "正在侦察书海…" : "帮我找下一本"}
            </button>
          </form>

          <div className="examples" aria-label="偏好示例">
            <span>试试这些：</span>
            {examples.map((example) => (
              <button
                type="button"
                key={example}
                onClick={() => setRequest(example)}
                disabled={isLoading}
              >
                {example}
              </button>
            ))}
          </div>
        </div>

        <aside className="promise-card" aria-label="推荐原则">
          <p className="card-kicker">推荐守则</p>
          <strong>宁可少一点，也不编一本。</strong>
          <ol>
            <li>理解你的具体口味</li>
            <li>搜索并核对真实作品</li>
            <li>标出证据和不确定信息</li>
          </ol>
        </aside>
      </section>

      <section className="results-region" aria-live="polite" aria-busy={isLoading}>
        {isLoading && <LoadingState />}
        {error && <ErrorState message={error} />}
        {result && <RecommendationResults result={result} />}
      </section>
    </main>
  );
}

function LoadingState() {
  return (
    <div className="state-panel loading-panel" role="status">
      <span className="book-loader" aria-hidden="true" />
      <div>
        <strong>正在理解口味、搜索候选并核对来源…</strong>
        <p>这个过程会调用真实的 AI 和网页搜索，通常需要一点时间。</p>
      </div>
    </div>
  );
}

function ErrorState({ message }: { message: string }) {
  return (
    <div className="state-panel error-panel" role="alert">
      <span aria-hidden="true">!</span>
      <div>
        <strong>这次没有顺利找到</strong>
        <p>{message}</p>
      </div>
    </div>
  );
}

function RecommendationResults({ result }: { result: RecommendationResponse }) {
  const profileTags = Array.from(
    new Set([
      ...result.profile.genres,
      ...result.profile.positive_aspects,
      ...result.profile.hard_exclusions.map((item) => `避雷：${item}`),
    ]),
  ).slice(0, 8);

  return (
    <div className="results-wrap">
      <div className="results-heading">
        <div>
          <p className="eyebrow">YOUR READING SHORTLIST</p>
          <h2>为你找到的下一本</h2>
        </div>
        {profileTags.length > 0 && (
          <div className="profile-tags" aria-label="识别出的阅读偏好">
            {profileTags.map((tag) => (
              <span key={tag}>{tag}</span>
            ))}
          </div>
        )}
      </div>

      {result.recommendations.length === 0 ? (
        <div className="state-panel empty-panel">
          <span aria-hidden="true">⌁</span>
          <div>
            <strong>这次没有足够可靠的推荐</strong>
            <p>我们没有找到同时满足偏好和证据要求的作品。可以放宽一个条件再试试。</p>
          </div>
        </div>
      ) : (
        <div className="recommendation-grid">
          {result.recommendations.map((book) => {
            const sourceUrl = book.official_url || book.sources[0]?.url;
            const reasons =
              book.reasons && book.reasons.length > 0
                ? book.reasons
                : book.match_reasons.map((text) => ({
                    text,
                    kind: "preference_inference" as const,
                    source_ids: [],
                  }));
            return (
              <article className="book-card" key={`${book.rank}-${book.title}`}>
                <div className="book-card-topline">
                  <span className="rank">#{book.rank}</span>
                  <span className={`verification ${book.verification_status}`}>
                    {verificationLabels[book.verification_status]}
                  </span>
                </div>
                <h3>{book.title}</h3>
                <p className="book-meta">
                  {book.author || "作者待确认"}
                  <span aria-hidden="true"> · </span>
                  {book.platform || "平台待确认"}
                  <span aria-hidden="true"> · </span>
                  {publicationLabels[book.publication_status]}
                </p>
                <div className="score-row">
                  <span>匹配度</span>
                  <strong>{Math.round(book.relevance_score)}</strong>
                  <span>/ 100</span>
                </div>
                {book.genre_tags.length > 0 && (
                  <div className="genre-tags">
                    {book.genre_tags.map((tag) => (
                      <span key={tag}>{tag}</span>
                    ))}
                  </div>
                )}
                <div className="reasons">
                  <p>为什么推荐</p>
                  <ul>
                    {reasons.map((reason) => (
                      <li key={`${reason.kind}-${reason.text}`}>
                        <span className={`reason-kind ${reason.kind}`}>
                          {reasonKindLabels[reason.kind]}
                        </span>
                        {reason.text}
                      </li>
                    ))}
                  </ul>
                </div>
                {book.uncertainties.length > 0 && (
                  <details>
                    <summary>仍需留意的信息</summary>
                    <ul>
                      {book.uncertainties.map((uncertainty) => (
                        <li key={uncertainty}>{uncertainty}</li>
                      ))}
                    </ul>
                  </details>
                )}
                {sourceUrl && (
                  <a className="source-link" href={sourceUrl} target="_blank" rel="noreferrer">
                    {book.official_url ? "查看原始平台" : "查看来源证据"}
                    <span aria-hidden="true">↗</span>
                  </a>
                )}
              </article>
            );
          })}
        </div>
      )}

      {result.warnings.length > 0 && (
        <div className="result-warning" role="status">
          {result.warnings.join(" ")}
        </div>
      )}

      <p className="provider-note">
        本次由 {result.providers.model} 分析，{result.providers.search} 检索。主观评价会与已核实元数据分开标注。
      </p>
    </div>
  );
}
