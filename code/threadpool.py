# Copyright (C) 2012-2013 Itay Brandes
# Based on lunixbochs's code: https://github.com/lunixbochs/meta/blob/master/snippets/python/threadpool.py

'''
A class that creates and manipulates a threadpool.
'''

from Queue import Queue, Empty
import threading
import traceback
import inspect
import logging
import time

class TerminatedException(Exception):
	pass

class ThreadPool:
	def __init__(self, max_threads, log_returns=False, catch_returns=False, logger=None, stack_size=0, return_queue=100):
		self.lock = threading.Lock()
		self.max = max_threads
		self.logger = logger or logging.getLogger('dummy')
		self.stack_size = stack_size
		self.log_returns = log_returns
		self.catch_returns = catch_returns
		self._terminated = False
		self._paused = False

		self.call_queue = Queue()
		self.returns = Queue(return_queue)
		self.spawn_workers()

	def __call__(self, func):
		def wrapper(*args, **kwargs):
			self.call_queue.put((func, args, kwargs))
		return wrapper
	
	def spawn_workers(self):
		for i in xrange(self.max):
			thread = threading.Thread(target=self.worker, args=(self.call_queue, ))
			thread.daemon = True
			thread.start()
	
	def worker(self, call):
		while True:
			func, args, kwargs = call.get() # get a func and args data
			try:
				self.processEvents()
				result = func(*args, **kwargs) # launches it
				self.processEvents()
				if self.catch_returns or self.log_returns:
					if inspect.isgenerator(result) or 'itertools' in str(result.__class__):
						for x in result:
							self.processEvents()
							self.returned(x)
					else:
						self.returned(result)
			except TerminatedException:
				pass
			except:
				self.logger.exception(traceback.format_exc())
			finally:
				call.task_done()
				
	def processEvents(self):
		if self._terminated:
			raise TerminatedException()
		while self._paused:
			time.sleep(0.1)
	
	def returned(self, result):
		if self.log_returns:
			self.logger.debug(result)
		if self.catch_returns:
			self.returns.put(result)
	
	def pop(self):
		"pop a result from the queue, blocks if we have none"
		if self.catch_returns:
			result = self.returns.get()
			self.returns.task_done()
			return result

	def iter(self):
		"acts as a generator, returning results as they happen. this method assumes you've already queued all of your calls."
		if not self.catch_returns:
			raise Exception

		while self.call_queue.unfinished_tasks > 0:
			try:
				yield self.returns.get(timeout=0.1)
			except Empty:
				pass
		
		while not self.returns.empty():
			yield self.returns.get()

	def flush(self):
		"clear and return the function returns queue"
		if self.catch_returns:
			results = tuple(self.returns.queue)
			self.returns = Queue()
			return results

		return ()
	
	def pause(self):
		self.logger.debug("Pausing...")
		self._paused = True
	def unpause(self):
		self.logger.debug("Unpausing...")
		self._paused = False

	def finish(self):
		"wait for queue to finish, then return flush()"
		self.call_queue.join()
		return self.flush()
	
	def terminate(self):
		"Terminates the object, blocks."
		self.logger.debug("Terminating...")
		self._terminated = True
		self.finish()
		
	def terminate_nowait(self):
		"Terminates the object, does not block."
		self.logger.debug("Terminating...")
		self._terminated = True
		self.flush()
	
	def isFinished(self):
		return not self.call_queue.unfinished_tasks