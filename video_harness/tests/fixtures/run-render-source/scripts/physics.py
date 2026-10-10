def validate_job(job):
    if job.get('physics', {}).get('lights', 4) < 1:
        raise ValueError('lights must be positive')
