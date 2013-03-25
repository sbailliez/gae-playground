
def truncate(s, limit): 
	""" 
	Truncates strings longer than limit to limit-3 characters, appending an 
	elipsis. At least one character will always be displayed, so the functional 
	minimum limit is 4. 
	"""  
	if len(s) <= limit: 
		return s 
	return '%s...' % s[:max(1, limit - 3)] 
