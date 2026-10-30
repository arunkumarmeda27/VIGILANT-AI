import { useState, type FormEvent } from 'react';

export const reviewStatusTransitions = {
  PENDING_REVIEW: ['IN_REVIEW'],
  IN_REVIEW: ['ADDITIONAL_INFORMATION_REQUIRED', 'ESCALATED', 'CLOSED'],
  ADDITIONAL_INFORMATION_REQUIRED: ['IN_REVIEW', 'ESCALATED', 'CLOSED'],
  ESCALATED: ['IN_REVIEW', 'CLOSED'],
  CLOSED: [],
} as const;

export type ReviewStatus = keyof typeof reviewStatusTransitions;

const requiredReasonStatuses = new Set<ReviewStatus>([
  'ADDITIONAL_INFORMATION_REQUIRED',
  'ESCALATED',
  'CLOSED',
]);

export function ReviewStatusControl({
  currentStatus,
  saving,
  onTransition,
}: {
  currentStatus: ReviewStatus;
  saving: boolean;
  onTransition: (status: ReviewStatus, reason: string) => Promise<void>;
}) {
  const choices = reviewStatusTransitions[currentStatus];
  const [nextStatus, setNextStatus] = useState<ReviewStatus | ''>('');
  const [reason, setReason] = useState('');
  const reasonRequired = nextStatus !== '' && requiredReasonStatuses.has(nextStatus);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!nextStatus || saving || (reasonRequired && !reason.trim())) return;
    await onTransition(nextStatus, reason.trim());
    setReason('');
    setNextStatus('');
  }

  return (
    <form className="assessment-assignment-form" onSubmit={submit}>
      <label htmlFor="review-status-transition">Review task status
        <select
          id="review-status-transition"
          required
          value={nextStatus}
          disabled={saving || choices.length === 0}
          onChange={event => setNextStatus(event.target.value as ReviewStatus | '')}
        >
          <option value="">Choose next status</option>
          {choices.map(status => (
            <option key={status} value={status}>{status.replaceAll('_', ' ')}</option>
          ))}
        </select>
      </label>
      <label htmlFor="review-status-reason">Reason{reasonRequired ? ' (required)' : ' (optional)'}
        <textarea
          id="review-status-reason"
          maxLength={2000}
          required={reasonRequired}
          value={reason}
          disabled={saving || choices.length === 0}
          onChange={event => setReason(event.target.value)}
        />
      </label>
      <button className="button primary" type="submit" disabled={saving || !nextStatus}>
        {saving ? 'Saving…' : 'Update review status'}
      </button>
      {choices.length === 0 && <p className="validation-meta">This review task is closed; no further status transitions are allowed.</p>}
    </form>
  );
}
