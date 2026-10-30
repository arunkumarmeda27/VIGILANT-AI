import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReviewStatusControl } from './ReviewStatusControl';

afterEach(cleanup);

describe('ReviewStatusControl', () => {
  it('requires a reason for escalation and submits the transition', async () => {
    const onTransition = vi.fn(async () => {});
    render(<ReviewStatusControl currentStatus="IN_REVIEW" saving={false} onTransition={onTransition} />);

    fireEvent.change(screen.getByLabelText('Review task status'), {
      target: { value: 'ESCALATED' },
    });
    const reason = screen.getByLabelText('Reason (required)');
    expect(reason.hasAttribute('required')).toBe(true);
    fireEvent.change(reason, { target: { value: 'Issuer review is unavailable.' } });
    fireEvent.submit(screen.getByRole('button', { name: 'Update review status' }).closest('form')!);

    expect(onTransition).toHaveBeenCalledWith('ESCALATED', 'Issuer review is unavailable.');
  });

  it('does not offer transitions from a closed task', () => {
    render(<ReviewStatusControl currentStatus="CLOSED" saving={false} onTransition={vi.fn(async () => {})} />);

    expect(screen.getByLabelText('Review task status').hasAttribute('disabled')).toBe(true);
    expect(screen.getByText(/This review task is closed/)).toBeTruthy();
  });
});
