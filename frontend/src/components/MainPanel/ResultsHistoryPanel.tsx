import type { InspectionResult, Timestamp } from '../../types/index';

export interface ResultHistoryItem {
  frameId: string;
  result: InspectionResult;
  timestamp: Timestamp;
  thumbnailUrl?: string;
}

interface ResultsHistoryPanelProps {
  results: ResultHistoryItem[];
}

function formatRelativeTime(timestamp: Timestamp): string {
  const seconds = Math.round((Date.now() - timestamp) / 1000);
  if (seconds < 60) return `${seconds}s`;
  return `${Math.round(seconds / 60)}m`;
}

export function ResultsHistoryPanel({ results }: ResultsHistoryPanelProps) {
  return (
    <aside className="bg-white dark:bg-[#2e2d2d] rounded-[10px] flex flex-col h-screen min-h-0">
      <div className="flex items-center justify-between px-4 py-3.5">
        <span className="text-[18px] font-semibold text-[#393939] dark:text-white">Frames</span>
      </div>
      <div className="flex flex-col gap-2.5 flex-1 min-h-0 px-2 overflow-y-scroll">
        {results.map((item) => (
          <div key={item.frameId} className="rounded-lg overflow-hidden shrink-0">
            <div className="h-30 bg-[#F7F7F7] dark:bg-[#6D6D6D] flex items-center justify-center">
              {item.thumbnailUrl ? (
                <img src={item.thumbnailUrl} alt={`Frame ${item.frameId}`} />
              ) : (
                <span className="text-[11px] text-[#9aa3af]">{item.frameId}</span>
              )}
            </div>
            <div className="flex justify-between items-center py-1.5 px-2">
              <span
                className={`${'text-[11px] font-bold py-0.5 px-2 rounded-full'} ${item.result === 'ok' ? 'bg-[rgba(30,158,99,0.12)] text-[#1e9e63]' : 'text-[11px] font-bold py-0.5 px-2 rounded-full bg-[rgba(214,69,69,0.12)] text-[#d64545]'}`}
              >
                {item.result}
              </span>
              <span className="text-[11px] text-[#9aa3af]">
                {formatRelativeTime(item.timestamp)}
              </span>
            </div>
          </div>
        ))}
      </div>
    </aside>
  );
}
