// 信心投票佇列 —— 對應原規格的 "Confidence Voting Queue"。
// 在前端就用「最近 N 幀的眾數」消除反光造成的單幀誤判 (073→078)。

export interface OcrFrame {
  text: string; // 正規化後的辨識字串，例如 "SV8A 217/187 SAR"
  confidence: number; // 模型回傳的此幀平均字元信心 0~1
}

export interface VoteResult {
  text: string;
  votes: number; // 勝出字串在視窗內出現次數
  windowSize: number; // 目前視窗大小
  agreement: number; // votes / windowSize，0~1
  avgConfidence: number; // 勝出字串各幀的平均信心
}

export class VotingQueue {
  private window: OcrFrame[] = [];

  constructor(
    private readonly size = 5, // 視窗幀數
    private readonly minVotes = 3, // 勝出門檻（眾數至少出現幾次）
    private readonly minConfidence = 0.85,
  ) {}

  /** 推入一幀；視窗滿則淘汰最舊的。 */
  push(frame: OcrFrame): void {
    if (!frame.text) return;
    this.window.push(frame);
    if (this.window.length > this.size) this.window.shift();
  }

  /** 嘗試取得收斂結果；未達門檻回 null（代表仍需更多幀或要走後端 fuzzy）。 */
  vote(): VoteResult | null {
    if (this.window.length < this.size) return null;

    const freq = new Map<string, OcrFrame[]>();
    for (const f of this.window) {
      const arr = freq.get(f.text) ?? [];
      arr.push(f);
      freq.set(f.text, arr);
    }

    let bestText = "";
    let bestFrames: OcrFrame[] = [];
    for (const [text, frames] of freq) {
      if (frames.length > bestFrames.length) {
        bestText = text;
        bestFrames = frames;
      }
    }

    if (bestFrames.length < this.minVotes) return null;

    const avgConfidence =
      bestFrames.reduce((s, f) => s + f.confidence, 0) / bestFrames.length;

    return {
      text: bestText,
      votes: bestFrames.length,
      windowSize: this.window.length,
      agreement: bestFrames.length / this.window.length,
      avgConfidence,
    };
  }

  /** 信心是否足以「前端直接採信」，否則交後端雙軌 fuzzy。 */
  isHighConfidence(r: VoteResult): boolean {
    return r.avgConfidence >= this.minConfidence && r.votes >= this.minVotes;
  }

  /** 收齊一張卡後清空，準備掃下一張。 */
  reset(): void {
    this.window = [];
  }
}
