import { fireEvent, render, screen } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import Chat from './chat';

const state = vi.hoisted(() => ({messages:[] as unknown[],sendMessage:vi.fn(),regenerate:vi.fn(),status:'ready',error:null as Error | null}));
vi.mock('@ai-sdk/react',() => ({useChat:() => state}));
beforeEach(() => {
  state.messages=[]; state.status='ready'; state.error=null;
  vi.clearAllMocks();
  Element.prototype.scrollIntoView = vi.fn();
});
it('renders a server-confirmed workout receipt with a link to Fitness',() => {
  state.messages=[{id:'response',role:'assistant',parts:[{type:'data-workout-saved',data:{id:'workout',performed_on:'2026-10-15',exercises:2,sets:3,already_recorded:false}}]}];
  render(<Chat/>);
  expect(screen.getByRole('status')).toHaveTextContent('Workout saved');
  expect(screen.getByRole('link',{name:'View in Fitness'})).toHaveAttribute('href','/fitness/');
});
it('retries the same message rather than submitting another log',() => {
  state.error=new Error('Connection lost');
  render(<Chat/>);
  fireEvent.click(screen.getByText('Retry message'));
  expect(state.regenerate).toHaveBeenCalledOnce();
  expect(state.sendMessage).not.toHaveBeenCalled();
});
it('blocks repeated submissions while a request is pending',() => {
  state.status='submitted';
  render(<Chat/>);
  fireEvent.change(screen.getByRole('textbox',{name:'Chat message'}),{target:{value:'Log today: press 60 lbs x 8'}});
  expect(screen.getByRole('button',{name:'Send message'})).toBeDisabled();
  fireEvent.keyDown(screen.getByRole('textbox'),{key:'Enter'});
  expect(state.sendMessage).not.toHaveBeenCalled();
});
