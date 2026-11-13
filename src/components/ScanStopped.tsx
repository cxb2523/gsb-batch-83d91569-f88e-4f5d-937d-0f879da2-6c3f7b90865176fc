import React from 'react';
import { ScanStage, ScanStopConclusion, StopReason } from '../model/scan-stop';
import { ScanModes } from '../model/scan-modes';

interface ScanStoppedProps {
    readonly conclusion: ScanStopConclusion;
    readonly scanModes: ScanModes;
    readonly onRestart: (scanModes: ScanModes) => void;
}

const stageLabel = (stage: ScanStage, likerPostIndex: number | null): string => {
    switch (stage) {
        case 'posts':
            return 'Post collection';
        case 'likers':
            return likerPostIndex === null
                ? 'Liker collection'
                : `Liker collection (post ${likerPostIndex})`;
        case 'following':
            return 'Following list collection';
        case 'followers':
            return 'Follower list collection';
        default:
            return stage;
    }
};

const reasonLabel = (reason: StopReason): string => {
    switch (reason) {
        case 'cursor':
            return 'Pagination cursor error';
        case 'rate_limit':
            return 'Rate limit';
        case 'auth':
            return 'Login expired';
        case 'challenge':
            return 'Challenge or checkpoint';
        case 'network':
            return 'Network error';
        case 'timeout':
            return 'Request timeout';
        case 'stopped':
            return 'Stopped';
        case 'bounds':
            return 'Scan limit reached';
        case 'http':
            return 'HTTP error';
        case 'invalid_response':
            return 'Invalid response';
        case 'unknown':
            return 'Unexpected failure';
        default:
            return reason;
    }
};

interface CountRow {
    readonly label: string;
    readonly value: number;
    readonly show: boolean;
}

export const ScanStopped = ({ conclusion, scanModes, onRestart }: ScanStoppedProps) => {
    const counts: readonly CountRow[] = [
        { label: 'Unique posts collected', value: conclusion.uniquePostCount, show: true },
        { label: 'Unique likers identified', value: conclusion.uniqueLikerCount, show: true },
        { label: 'Following accounts collected', value: conclusion.followingCount, show: true },
        {
            label: 'Follower accounts collected',
            value: conclusion.followerCount,
            show: scanModes.followerAnalysis,
        },
    ];

    return (
        <main className='scan-stopped-container' aria-live='assertive'>
            <section className='scan-stopped'>
                <h1>Scan stopped early</h1>
                <p className='scan-stopped-subtitle'>
                    No further requests were made. The partial data below is diagnostic only: it was not saved and
                    cannot be viewed as a leaderboard.
                </p>

                <dl className='stop-summary'>
                    <div className='stop-summary-row'>
                        <dt>Failed stage</dt>
                        <dd>{stageLabel(conclusion.stage, conclusion.likerPostIndex)}</dd>
                    </div>
                    <div className='stop-summary-row'>
                        <dt>Reason</dt>
                        <dd>{reasonLabel(conclusion.reason)}</dd>
                    </div>
                </dl>
                <p className='stop-detail'>{conclusion.errorMessage}</p>
                {conclusion.reason === 'rate_limit' && conclusion.retryAt !== null && (
                    <p className='stop-retry' role='status'>
                        Do not retry before {new Date(conclusion.retryAt).toLocaleString()}.
                    </p>
                )}

                <h2>Collected before the stop</h2>
                <ul className='stop-counts'>
                    {counts.filter(row => row.show).map(row => (
                        <li key={row.label} className='stop-count-row'>
                            <span>{row.label}</span>
                            <strong>{row.value}</strong>
                        </li>
                    ))}
                </ul>

                <div className='controls'>
                    <button
                        type='button'
                        className='button-control'
                        onClick={() => onRestart(scanModes)}
                    >
                        Start a new scan
                    </button>
                </div>
                <p className='scanning-detail'>
                    Starting again discards this conclusion and collects a fresh scan from the beginning.
                </p>
            </section>
        </main>
    );
};
